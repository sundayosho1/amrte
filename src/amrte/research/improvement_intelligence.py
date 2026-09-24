from __future__ import annotations

import hashlib
import json
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from amrte.core.composition import ComponentCapabilities, ComponentMetadata, ComponentType
from amrte.core.identity import deterministic_id
from amrte.core.types import HealthStatus
from amrte.research.evidence_ledger import research_decision_evidence_record_schema_identity
from amrte.research.outcome_performance import (
    ResearchOutcomeAttribution,
    ResearchPerformanceSnapshot,
    research_outcome_attribution_schema_identity,
    research_outcome_policy_identity,
    research_outcome_window_schema_identity,
    research_performance_snapshot_schema_identity,
)


RESEARCH_IMPROVEMENT_RUNTIME_VERSION = "1.0"
IMPROVEMENT_CANDIDATE_SCHEMA_VERSION = "1.0"
RESEARCH_FAILURE_CLUSTER_SCHEMA_VERSION = "1.0"
RESEARCH_IMPROVEMENT_SNAPSHOT_SCHEMA_VERSION = "1.0"
RESEARCH_IMPROVEMENT_POLICY_VERSION = "1.0"


class FindingType(Enum):
    STRATEGY_DEGRADATION = "STRATEGY_DEGRADATION"
    STRATEGY_INSTABILITY = "STRATEGY_INSTABILITY"
    REGIME_SENSITIVITY = "REGIME_SENSITIVITY"
    SESSION_SENSITIVITY = "SESSION_SENSITIVITY"
    PARAMETER_SENSITIVITY = "PARAMETER_SENSITIVITY"
    FEATURE_LOW_INFORMATION = "FEATURE_LOW_INFORMATION"
    FEATURE_INSTABILITY = "FEATURE_INSTABILITY"
    SCORE_CALIBRATION_CONCERN = "SCORE_CALIBRATION_CONCERN"
    ARBITRATION_CONFLICT_PATTERN = "ARBITRATION_CONFLICT_PATTERN"
    NO_ACTION_PATTERN = "NO_ACTION_PATTERN"
    REJECTION_PATTERN = "REJECTION_PATTERN"
    PROTECTION_INTERVENTION_PATTERN = "PROTECTION_INTERVENTION_PATTERN"
    RESTRICTION_PATTERN = "RESTRICTION_PATTERN"
    DATA_QUALITY_FAILURE_PATTERN = "DATA_QUALITY_FAILURE_PATTERN"
    PORTFOLIO_RESTRICTION_PATTERN = "PORTFOLIO_RESTRICTION_PATTERN"
    CORRELATION_DEPENDENCY_PATTERN = "CORRELATION_DEPENDENCY_PATTERN"
    CONFIGURATION_SENSITIVITY = "CONFIGURATION_SENSITIVITY"
    OUTCOME_INSTABILITY = "OUTCOME_INSTABILITY"
    RESEARCH_EVIDENCE_GAP = "RESEARCH_EVIDENCE_GAP"
    REPEATED_FAILURE_CLUSTER = "REPEATED_FAILURE_CLUSTER"
    POTENTIAL_RESEARCH_OPPORTUNITY = "POTENTIAL_RESEARCH_OPPORTUNITY"


class FindingDomain(Enum):
    DATA = "DATA"
    INTELLIGENCE = "INTELLIGENCE"
    STRATEGY = "STRATEGY"
    SCORING = "SCORING"
    ARBITRATION = "ARBITRATION"
    RISK = "RISK"
    PORTFOLIO = "PORTFOLIO"
    PROTECTION = "PROTECTION"
    ORCHESTRATION = "ORCHESTRATION"
    EVIDENCE = "EVIDENCE"
    OUTCOME_ANALYTICS = "OUTCOME_ANALYTICS"
    CONFIGURATION = "CONFIGURATION"
    RELIABILITY = "RELIABILITY"


class EvidenceStrength(Enum):
    INSUFFICIENT = "INSUFFICIENT"
    WEAK = "WEAK"
    MODERATE = "MODERATE"
    STRONG = "STRONG"


class CandidateStatus(Enum):
    IDENTIFIED = "IDENTIFIED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    INVESTIGATION_RECOMMENDED = "INVESTIGATION_RECOMMENDED"
    VALIDATION_REQUIRED = "VALIDATION_REQUIRED"
    SUPERSEDED = "SUPERSEDED"
    DISMISSED_BY_EVIDENCE = "DISMISSED_BY_EVIDENCE"


class Recommendation(Enum):
    INVESTIGATE = "INVESTIGATE"
    REVALIDATE = "REVALIDATE"
    COMPARE = "COMPARE"
    REVIEW_CONFIGURATION = "REVIEW_CONFIGURATION"
    REVIEW_FEATURE = "REVIEW_FEATURE"
    REVIEW_FILTER = "REVIEW_FILTER"
    REVIEW_THRESHOLD = "REVIEW_THRESHOLD"
    REVIEW_DATA_SOURCE = "REVIEW_DATA_SOURCE"
    REVIEW_RESTRICTION = "REVIEW_RESTRICTION"
    REVIEW_STRATEGY_LOGIC = "REVIEW_STRATEGY_LOGIC"
    REVIEW_PORTFOLIO_RULE = "REVIEW_PORTFOLIO_RULE"
    REVIEW_PROTECTION_RULE = "REVIEW_PROTECTION_RULE"
    COLLECT_MORE_EVIDENCE = "COLLECT_MORE_EVIDENCE"
    NO_CHANGE_RECOMMENDED = "NO_CHANGE_RECOMMENDED"


@dataclass(frozen=True)
class ResearchImprovementPolicy:
    policy_id: str
    version: str
    minimum_evidence: int
    moderate_evidence: int
    strong_evidence: int
    degradation_threshold: Decimal
    sensitivity_threshold: Decimal
    instability_threshold: Decimal
    practical_significance_threshold: Decimal
    duplicate_policy: str
    exploratory_strength_cap: str
    safety_first_domains: tuple[str, ...]
    finding_taxonomy: tuple[str, ...]
    recommendation_taxonomy: tuple[str, ...]
    policy_identity: str

    @classmethod
    def current(cls) -> "ResearchImprovementPolicy":
        taxonomy = tuple(item.value for item in FindingType)
        recommendations = tuple(item.value for item in Recommendation)
        payload = {
            "policy_id": "P49_RESEARCH_IMPROVEMENT_POLICY",
            "version": RESEARCH_IMPROVEMENT_POLICY_VERSION,
            "minimum_evidence": 3,
            "moderate_evidence": 5,
            "strong_evidence": 8,
            "degradation_threshold": "0.02000000",
            "sensitivity_threshold": "0.04000000",
            "instability_threshold": "0.06000000",
            "practical_significance_threshold": "0.01000000",
            "duplicate_policy": "unique-attribution-ids-and-window-ids-only",
            "exploratory_strength_cap": EvidenceStrength.WEAK.value,
            "safety_first_domains": (
                FindingDomain.DATA.value,
                FindingDomain.EVIDENCE.value,
                FindingDomain.RELIABILITY.value,
                FindingDomain.PROTECTION.value,
                FindingDomain.OUTCOME_ANALYTICS.value,
            ),
            "finding_taxonomy": taxonomy,
            "recommendation_taxonomy": recommendations,
        }
        return cls(
            payload["policy_id"],
            payload["version"],
            int(payload["minimum_evidence"]),
            int(payload["moderate_evidence"]),
            int(payload["strong_evidence"]),
            Decimal(payload["degradation_threshold"]),
            Decimal(payload["sensitivity_threshold"]),
            Decimal(payload["instability_threshold"]),
            Decimal(payload["practical_significance_threshold"]),
            payload["duplicate_policy"],
            payload["exploratory_strength_cap"],
            tuple(payload["safety_first_domains"]),
            taxonomy,
            recommendations,
            _sha256_json(payload),
        )


@dataclass(frozen=True)
class ImprovementCandidate:
    candidate_id: str
    schema_version: str
    schema_identity: str
    component_type: str
    component_id: str
    component_version: str
    finding_type: str
    finding_domain: str
    finding_summary: str
    finding_detail: str
    finding_kind: str
    evidence_refs: tuple[str, ...]
    supporting_evidence_refs: tuple[str, ...]
    contradicting_evidence_refs: tuple[str, ...]
    evidence_count: int
    independent_window_count: int
    affected_population: Mapping[str, Any]
    comparison_population: Mapping[str, Any]
    cohort_refs: tuple[str, ...]
    outcome_refs: tuple[str, ...]
    source_snapshot_ids: tuple[str, ...]
    source_p47_evidence_ids: tuple[str, ...]
    evidence_strength: str
    confidence_classification: str
    effect_direction: str
    effect_magnitude: Decimal | None
    stability: str
    limitations: tuple[str, ...]
    confounders: tuple[str, ...]
    warnings: tuple[str, ...]
    recommended_investigation: str
    proposed_hypothesis: Mapping[str, Any]
    investigation_priority: str
    priority_reasons: tuple[str, ...]
    automatic_change: bool
    validation_required: bool
    candidate_status: str
    supersedes_candidate_id: str | None
    configuration_identity: str
    analysis_policy_identity: str
    as_of: datetime
    knowledge_cutoff: datetime
    exploratory: bool
    candidate_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "affected_population", MappingProxyType(dict(self.affected_population)))
        object.__setattr__(self, "comparison_population", MappingProxyType(dict(self.comparison_population)))
        object.__setattr__(self, "proposed_hypothesis", MappingProxyType(dict(self.proposed_hypothesis)))


@dataclass(frozen=True)
class ResearchFailureCluster:
    cluster_id: str
    schema_version: str
    schema_identity: str
    finding_type: str
    member_evidence_ids: tuple[str, ...]
    component_ids: tuple[str, ...]
    strategy_ids: tuple[str, ...]
    regimes: tuple[str, ...]
    sessions: tuple[str, ...]
    sample_count: int
    time_range: tuple[datetime | None, datetime | None]
    reason_distribution: Mapping[str, int]
    evidence_strength: str
    cluster_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_distribution", MappingProxyType(dict(self.reason_distribution)))


@dataclass(frozen=True)
class ResearchImprovementSnapshot:
    snapshot_id: str
    schema_version: str
    schema_identity: str
    analysis_as_of: datetime
    source_p48_snapshot_ids: tuple[str, ...]
    source_p47_ledger_range: tuple[int, int] | None
    candidate_ids: tuple[str, ...]
    candidate_count: int
    finding_distribution: Mapping[str, int]
    domain_distribution: Mapping[str, int]
    evidence_strength_distribution: Mapping[str, int]
    investigation_priority_distribution: Mapping[str, int]
    strategy_findings: tuple[str, ...]
    regime_findings: tuple[str, ...]
    session_findings: tuple[str, ...]
    data_quality_findings: tuple[str, ...]
    no_action_findings: tuple[str, ...]
    restriction_findings: tuple[str, ...]
    portfolio_findings: tuple[str, ...]
    reliability_findings: tuple[str, ...]
    insufficient_evidence_count: int
    contradictory_evidence_count: int
    failure_cluster_ids: tuple[str, ...]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    policy_identity: str
    configuration_identity: str
    pipeline_identity: str
    snapshot_fingerprint: str
    financial_execution: str = "NONE"

    def __post_init__(self) -> None:
        for name in (
            "finding_distribution",
            "domain_distribution",
            "evidence_strength_distribution",
            "investigation_priority_distribution",
        ):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))


@dataclass(frozen=True)
class ResearchImprovementRecoveryState:
    schema_version: str
    runtime_version: str
    policy_identity: str
    configuration_identity: str
    analysis_cutoff: datetime
    recovery_epoch: int
    processed_p48_snapshot_ids: tuple[str, ...]
    processed_attribution_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    failure_cluster_ids: tuple[str, ...]
    improvement_snapshot_ids: tuple[str, ...]
    candidates: tuple[ImprovementCandidate, ...]
    clusters: tuple[ResearchFailureCluster, ...]
    snapshots: tuple[ResearchImprovementSnapshot, ...]


class ResearchImprovementRuntime:
    """Prompt 49 evidence-to-hypothesis runtime.

    The runtime produces research candidates only. It cannot mutate strategy,
    configuration, protection, portfolio, or execution policy.
    """

    def __init__(
        self,
        *,
        clock: Any,
        audit: Any,
        policy: ResearchImprovementPolicy | None = None,
        configuration_identity: str = "P49_RESEARCH_IMPROVEMENT_DEFAULT",
        storage_root: Path = Path("data/research-improvement-intelligence"),
        maximum_candidates: int = 4096,
        maximum_clusters: int = 1024,
        maximum_snapshots: int = 512,
        maximum_query_limit: int = 100,
    ) -> None:
        self.clock = clock
        self.audit = audit
        self.policy = policy or ResearchImprovementPolicy.current()
        self.configuration_identity = configuration_identity
        self.storage_root = Path(storage_root)
        self.maximum_candidates = max(1, maximum_candidates)
        self.maximum_clusters = max(1, maximum_clusters)
        self.maximum_snapshots = max(1, maximum_snapshots)
        self.maximum_query_limit = max(1, min(maximum_query_limit, 500))
        self.candidates: OrderedDict[str, ImprovementCandidate] = OrderedDict()
        self.clusters: OrderedDict[str, ResearchFailureCluster] = OrderedDict()
        self.snapshots: OrderedDict[str, ResearchImprovementSnapshot] = OrderedDict()
        self.processed_p48_snapshot_ids: set[str] = set()
        self.processed_attribution_ids: set[str] = set()
        self.recovery_restricted = False
        self.metrics = {
            "p48_snapshots_processed": 0,
            "attributions_analyzed": 0,
            "findings_generated": 0,
            "findings_suppressed_for_insufficiency": 0,
            "no_action_findings": 0,
            "restriction_findings": 0,
            "strategy_findings": 0,
            "data_quality_findings": 0,
            "portfolio_findings": 0,
            "reliability_findings": 0,
            "failure_clusters": 0,
            "contradictory_evidence_count": 0,
            "superseded_candidate_count": 0,
            "recovery_count": 0,
            "recovery_divergence": 0,
        }
        self.initialize_component(None)

    def initialize_component(self, context: Any) -> None:
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self._record("research_improvement_runtime_initialized", {"policy_identity": self.policy.policy_identity})

    def analyze(
        self,
        snapshot: ResearchPerformanceSnapshot,
        attributions: Iterable[ResearchOutcomeAttribution],
        *,
        analysis_as_of: datetime | None = None,
        source_p47_ledger_range: tuple[int, int] | None = None,
    ) -> ResearchImprovementSnapshot:
        as_of = analysis_as_of or self.clock.now()
        self._record("improvement_analysis_started", {"snapshot_id": snapshot.snapshot_id})
        items = tuple(sorted(_dedupe_attributions(tuple(attributions)), key=lambda item: item.attribution_id))
        reasons = self._validate_inputs(snapshot, items, as_of)
        if reasons:
            raise ValueError(";".join(reasons))
        generated = list(self._generate_candidates(snapshot, items, as_of))
        clusters = self._clusters(generated, items, as_of)
        for cluster in clusters:
            self.clusters[cluster.cluster_id] = cluster
        self._trim(self.clusters, self.maximum_clusters)
        for candidate in generated:
            self.candidates[candidate.candidate_id] = candidate
        self._trim(self.candidates, self.maximum_candidates)
        self.processed_p48_snapshot_ids.add(snapshot.snapshot_id)
        self.processed_attribution_ids.update(item.attribution_id for item in items)
        self.metrics["p48_snapshots_processed"] += 1
        self.metrics["attributions_analyzed"] += len(items)
        self.metrics["findings_generated"] += len(generated)
        self.metrics["failure_clusters"] = len(self.clusters)
        self.metrics["contradictory_evidence_count"] += sum(1 for item in generated if item.contradicting_evidence_refs)
        improvement_snapshot = self._snapshot(tuple(generated), tuple(clusters), snapshot, as_of, source_p47_ledger_range)
        self.snapshots[improvement_snapshot.snapshot_id] = improvement_snapshot
        self._trim(self.snapshots, self.maximum_snapshots)
        self._record("improvement_analysis_completed", {"snapshot_id": improvement_snapshot.snapshot_id, "candidates": len(generated)})
        return improvement_snapshot

    def query_candidates(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        finding_type: str | None = None,
        domain: str | None = None,
    ) -> tuple[ImprovementCandidate, ...]:
        limit = max(1, min(limit, self.maximum_query_limit))
        selected = [
            item
            for item in self.candidates.values()
            if (finding_type is None or item.finding_type == finding_type) and (domain is None or item.finding_domain == domain)
        ]
        return tuple(selected[max(0, offset) : max(0, offset) + limit])

    def get_candidate(self, candidate_id: str) -> ImprovementCandidate:
        return self.candidates[candidate_id]

    def supersede_candidate(
        self,
        candidate_id: str,
        *,
        reason: str,
        as_of: datetime | None = None,
    ) -> ImprovementCandidate:
        original = self.get_candidate(candidate_id)
        payload = {
            "original": candidate_id,
            "reason": reason,
            "policy": self.policy.policy_identity,
            "configuration": self.configuration_identity,
        }
        fingerprint = _sha256_json(payload)
        candidate = ImprovementCandidate(
            deterministic_id("p49_improvement_candidate", fingerprint),
            IMPROVEMENT_CANDIDATE_SCHEMA_VERSION,
            improvement_candidate_schema_identity(),
            original.component_type,
            original.component_id,
            original.component_version,
            original.finding_type,
            original.finding_domain,
            f"Supersedes {candidate_id}: {reason}",
            original.finding_detail,
            original.finding_kind,
            original.evidence_refs,
            original.supporting_evidence_refs,
            original.contradicting_evidence_refs,
            original.evidence_count,
            original.independent_window_count,
            original.affected_population,
            original.comparison_population,
            original.cohort_refs,
            original.outcome_refs,
            original.source_snapshot_ids,
            original.source_p47_evidence_ids,
            original.evidence_strength,
            original.confidence_classification,
            original.effect_direction,
            original.effect_magnitude,
            original.stability,
            original.limitations,
            original.confounders,
            (*original.warnings, "P49_CANDIDATE_SUPERSEDED"),
            Recommendation.REVALIDATE.value,
            original.proposed_hypothesis,
            original.investigation_priority,
            original.priority_reasons,
            False,
            True,
            CandidateStatus.SUPERSEDED.value,
            candidate_id,
            self.configuration_identity,
            self.policy.policy_identity,
            as_of or self.clock.now(),
            original.knowledge_cutoff,
            original.exploratory,
            fingerprint,
        )
        self.candidates[candidate.candidate_id] = candidate
        self.metrics["superseded_candidate_count"] += 1
        self._record("improvement_candidate_superseded", {"candidate_id": candidate.candidate_id, "supersedes": candidate_id})
        return candidate

    def recovery_state(self, recovery_epoch: int, analysis_cutoff: datetime | None = None) -> ResearchImprovementRecoveryState:
        return ResearchImprovementRecoveryState(
            RESEARCH_IMPROVEMENT_SNAPSHOT_SCHEMA_VERSION,
            RESEARCH_IMPROVEMENT_RUNTIME_VERSION,
            self.policy.policy_identity,
            self.configuration_identity,
            analysis_cutoff or self.clock.now(),
            recovery_epoch,
            tuple(sorted(self.processed_p48_snapshot_ids)),
            tuple(sorted(self.processed_attribution_ids)),
            tuple(self.candidates),
            tuple(self.clusters),
            tuple(self.snapshots),
            tuple(self.candidates.values()),
            tuple(self.clusters.values()),
            tuple(self.snapshots.values()),
        )

    def restore(self, state: ResearchImprovementRecoveryState, recovery_epoch: int) -> bool:
        self.metrics["recovery_count"] += 1
        self._record("improvement_recovery_started", {"recovery_epoch": recovery_epoch})
        if (
            state.runtime_version != RESEARCH_IMPROVEMENT_RUNTIME_VERSION
            or state.policy_identity != self.policy.policy_identity
            or state.configuration_identity != self.configuration_identity
            or state.recovery_epoch != recovery_epoch
        ):
            self.recovery_restricted = True
            self.metrics["recovery_divergence"] += 1
            self._record("improvement_recovery_failed", {"reason": "P49_RECOVERY_IDENTITY_MISMATCH"})
            return False
        self.candidates = OrderedDict((item.candidate_id, item) for item in state.candidates)
        self.clusters = OrderedDict((item.cluster_id, item) for item in state.clusters)
        self.snapshots = OrderedDict((item.snapshot_id, item) for item in state.snapshots)
        self.processed_p48_snapshot_ids = set(state.processed_p48_snapshot_ids)
        self.processed_attribution_ids = set(state.processed_attribution_ids)
        self.recovery_restricted = False
        self._record("improvement_recovery_completed", {"candidates": len(self.candidates), "clusters": len(self.clusters)})
        return True

    def replay_fingerprint(self) -> str:
        return deterministic_id(
            "p49_improvement_replay",
            self.policy.policy_identity,
            *self.candidates,
            *self.clusters,
            *self.snapshots,
        )

    def incremental_equals_full_rebuild(self) -> bool:
        latest = next(reversed(self.snapshots.values()), None) if self.snapshots else None
        if latest is None:
            return True
        rebuilt = ResearchImprovementRuntime(clock=self.clock, audit=None, policy=self.policy, configuration_identity=self.configuration_identity, storage_root=self.storage_root)
        rebuilt.candidates = OrderedDict((candidate_id, self.candidates[candidate_id]) for candidate_id in latest.candidate_ids if candidate_id in self.candidates)
        rebuilt.clusters = OrderedDict((cluster_id, self.clusters[cluster_id]) for cluster_id in latest.failure_cluster_ids if cluster_id in self.clusters)
        if len(rebuilt.candidates) != len(latest.candidate_ids) or len(rebuilt.clusters) != len(latest.failure_cluster_ids):
            return False
        rebuilt_snapshot = rebuilt._snapshot(
            tuple(rebuilt.candidates.values()),
            tuple(rebuilt.clusters.values()),
            _snapshot_stub(latest),
            latest.analysis_as_of,
            latest.source_p47_ledger_range,
        )
        return rebuilt_snapshot.snapshot_fingerprint == latest.snapshot_fingerprint

    def diagnostics(self) -> dict[str, Any]:
        latest = next(reversed(self.snapshots.values()), None) if self.snapshots else None
        return {
            "runtime_version": RESEARCH_IMPROVEMENT_RUNTIME_VERSION,
            "candidate_schema_version": IMPROVEMENT_CANDIDATE_SCHEMA_VERSION,
            "candidate_schema_identity": improvement_candidate_schema_identity(),
            "failure_cluster_schema_version": RESEARCH_FAILURE_CLUSTER_SCHEMA_VERSION,
            "failure_cluster_schema_identity": research_failure_cluster_schema_identity(),
            "snapshot_schema_version": RESEARCH_IMPROVEMENT_SNAPSHOT_SCHEMA_VERSION,
            "snapshot_schema_identity": research_improvement_snapshot_schema_identity(),
            "policy_identity": self.policy.policy_identity,
            "policy": _jsonable(self.policy),
            "candidate_count": len(self.candidates),
            "failure_cluster_count": len(self.clusters),
            "snapshot_count": len(self.snapshots),
            "latest_snapshot_id": latest.snapshot_id if latest else None,
            "metrics": dict(self.metrics),
            "runtime_health": self.component_health(None).name,
            "input_evidence_health": "AVAILABLE" if self.processed_p48_snapshot_ids else "INSUFFICIENT_EVIDENCE",
            "analysis_availability": "AVAILABLE" if self.snapshots else "NO_IMPROVEMENT_CANDIDATE",
            "finding_availability": "AVAILABLE" if self.candidates else "NO_IMPROVEMENT_CANDIDATE",
            "financial_execution": "NONE",
            "memory": {
                "candidates": len(self.candidates),
                "candidate_limit": self.maximum_candidates,
                "clusters": len(self.clusters),
                "cluster_limit": self.maximum_clusters,
                "snapshots": len(self.snapshots),
                "snapshot_limit": self.maximum_snapshots,
            },
        }

    def component_ready(self, context: Any) -> bool:
        return not self.recovery_restricted

    def component_health(self, context: Any) -> HealthStatus:
        return HealthStatus.RESTRICTED if self.recovery_restricted else HealthStatus.HEALTHY

    def _validate_inputs(
        self,
        snapshot: ResearchPerformanceSnapshot,
        attributions: tuple[ResearchOutcomeAttribution, ...],
        analysis_as_of: datetime,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if snapshot.schema_version != "1.0" or snapshot.schema_identity != research_performance_snapshot_schema_identity():
            reasons.append("P49_P48_SNAPSHOT_SCHEMA_MISMATCH")
        if snapshot.policy_identity != research_outcome_policy_identity():
            reasons.append("P49_P48_POLICY_MISMATCH")
        if snapshot.as_of > analysis_as_of:
            reasons.append("P49_FUTURE_P48_SNAPSHOT")
        if not snapshot.snapshot_fingerprint:
            reasons.append("P49_P48_SNAPSHOT_FINGERPRINT_MISSING")
        for item in attributions:
            if item.schema_version != "1.0" or item.schema_identity != research_outcome_attribution_schema_identity():
                reasons.append("P49_ATTRIBUTION_SCHEMA_MISMATCH")
            if item.outcome_policy_identity != snapshot.policy_identity:
                reasons.append("P49_ATTRIBUTION_POLICY_MISMATCH")
            if not item.attribution_fingerprint:
                reasons.append("P49_ATTRIBUTION_FINGERPRINT_MISSING")
            if item.financial_execution != "NONE" or item.causal_claim:
                reasons.append("P49_ATTRIBUTION_AUTHORITY_MISMATCH")
        return tuple(dict.fromkeys(reasons))

    def _generate_candidates(
        self,
        snapshot: ResearchPerformanceSnapshot,
        attributions: tuple[ResearchOutcomeAttribution, ...],
        as_of: datetime,
    ) -> tuple[ImprovementCandidate, ...]:
        candidates: list[ImprovementCandidate] = []
        if snapshot.sample_sufficiency == "INSUFFICIENT_EVIDENCE" or len(attributions) < self.policy.minimum_evidence:
            candidates.append(
                self._candidate(
                    FindingType.RESEARCH_EVIDENCE_GAP,
                    FindingDomain.EVIDENCE,
                    attributions,
                    snapshot,
                    "Outcome evidence is below P49 minimum evidence threshold.",
                    "Collect more mature P48 outcome evidence before drawing research-behavior conclusions.",
                    Recommendation.COLLECT_MORE_EVIDENCE,
                    EvidenceStrength.INSUFFICIENT,
                    effect=None,
                    status=CandidateStatus.INSUFFICIENT_EVIDENCE,
                    warnings=("P49_INSUFFICIENT_EVIDENCE",),
                )
            )
            self.metrics["findings_suppressed_for_insufficiency"] += 1
            self._record("insufficient_improvement_evidence", {"snapshot_id": snapshot.snapshot_id})
            return tuple(candidates)
        candidates.extend(self._strategy_degradation(snapshot, attributions))
        candidates.extend(self._sensitivity(snapshot, attributions, "regime_at_decision", FindingType.REGIME_SENSITIVITY, FindingDomain.STRATEGY))
        candidates.extend(self._sensitivity(snapshot, attributions, "session_at_decision", FindingType.SESSION_SENSITIVITY, FindingDomain.STRATEGY))
        candidates.extend(self._sensitivity(snapshot, attributions, "configuration_identity", FindingType.CONFIGURATION_SENSITIVITY, FindingDomain.CONFIGURATION))
        candidates.extend(self._score_band(snapshot, attributions))
        candidates.extend(self._classification_patterns(snapshot, attributions))
        candidates.extend(self._data_quality(snapshot, attributions))
        candidates.extend(self._portfolio(snapshot, attributions))
        candidates.extend(self._instability(snapshot, attributions))
        if not candidates:
            self._record("improvement_analysis_completed", {"snapshot_id": snapshot.snapshot_id, "result": "NO_IMPROVEMENT_CANDIDATE"})
        return tuple(candidates)

    def _strategy_degradation(
        self,
        snapshot: ResearchPerformanceSnapshot,
        attributions: tuple[ResearchOutcomeAttribution, ...],
    ) -> tuple[ImprovementCandidate, ...]:
        global_values = _changes(attributions)
        global_mean = _mean(global_values)
        if global_mean is None:
            return ()
        result = []
        for key, group in _group(attributions, lambda item: (item.strategy_id, item.strategy_version)).items():
            values = _changes(group)
            mean = _mean(values)
            if mean is None or len(values) < self.policy.minimum_evidence:
                continue
            delta = _q(mean - global_mean)
            if delta <= -self.policy.degradation_threshold:
                result.append(
                    self._candidate(
                        FindingType.STRATEGY_DEGRADATION,
                        FindingDomain.STRATEGY,
                        group,
                        snapshot,
                        f"Strategy {key[0]} version {key[1]} underperformed its predefined all-strategy reference cohort.",
                        "Reference is the P48 population available at the same analysis cutoff; strategy versions remain isolated.",
                        Recommendation.REVALIDATE,
                        self._strength(group, abs(delta)),
                        effect=delta,
                        affected={"strategy_id": key[0], "strategy_version": key[1], "mean": str(mean)},
                        comparison={"reference": "all_strategy_population", "mean": str(global_mean)},
                    )
                )
                self.metrics["strategy_findings"] += 1
        return tuple(result)

    def _sensitivity(
        self,
        snapshot: ResearchPerformanceSnapshot,
        attributions: tuple[ResearchOutcomeAttribution, ...],
        field: str,
        finding_type: FindingType,
        domain: FindingDomain,
    ) -> tuple[ImprovementCandidate, ...]:
        groups = _group(attributions, lambda item: (str(getattr(item, field)),))
        means = {key: _mean(_changes(tuple(items))) for key, items in groups.items() if len(_changes(tuple(items))) >= self.policy.minimum_evidence}
        means = {key: value for key, value in means.items() if value is not None}
        if len(means) < 2:
            return ()
        best = max(means.items(), key=lambda item: item[1])
        worst = min(means.items(), key=lambda item: item[1])
        spread = _q(best[1] - worst[1])
        if spread < self.policy.sensitivity_threshold:
            return ()
        affected = tuple(groups[worst[0]])
        result = self._candidate(
            finding_type,
            domain,
            affected,
            snapshot,
            f"{field} cohort {worst[0][0]} shows lower research behavior than comparison cohort {best[0][0]}.",
            "This is a sensitivity hypothesis, not a global generalization or validated improvement.",
            Recommendation.REVALIDATE,
            self._strength(affected, spread),
            effect=-spread,
            affected={field: worst[0][0], "mean": str(worst[1])},
            comparison={field: best[0][0], "mean": str(best[1])},
            exploratory=len(means) > 3,
        )
        if finding_type is FindingType.REGIME_SENSITIVITY:
            self.metrics["strategy_findings"] += 1
        return (result,)

    def _score_band(self, snapshot: ResearchPerformanceSnapshot, attributions: tuple[ResearchOutcomeAttribution, ...]) -> tuple[ImprovementCandidate, ...]:
        return self._sensitivity(snapshot, attributions, "score_band", FindingType.SCORE_CALIBRATION_CONCERN, FindingDomain.SCORING)

    def _classification_patterns(self, snapshot: ResearchPerformanceSnapshot, attributions: tuple[ResearchOutcomeAttribution, ...]) -> tuple[ImprovementCandidate, ...]:
        result = []
        for classification, finding, domain, recommendation in (
            ("NO_ACTION", FindingType.NO_ACTION_PATTERN, FindingDomain.ORCHESTRATION, Recommendation.REVIEW_FILTER),
            ("RESTRICTED", FindingType.RESTRICTION_PATTERN, FindingDomain.PROTECTION, Recommendation.REVIEW_RESTRICTION),
            ("REJECTED", FindingType.REJECTION_PATTERN, FindingDomain.ORCHESTRATION, Recommendation.INVESTIGATE),
            ("FAILED", FindingType.REPEATED_FAILURE_CLUSTER, FindingDomain.RELIABILITY, Recommendation.INVESTIGATE),
        ):
            group = tuple(item for item in attributions if item.decision_classification == classification)
            if len(group) >= self.policy.minimum_evidence:
                result.append(
                    self._candidate(
                        finding,
                        domain,
                        group,
                        snapshot,
                        f"{classification} decisions form a repeated evidence-backed cluster.",
                        f"{classification} remains in denominators and is not interpreted as a missed trade or strategy defect.",
                        recommendation,
                        self._strength(group, Decimal(len(group)) / Decimal(max(1, len(attributions)))),
                        effect=Decimal(len(group)),
                        affected={"classification": classification, "count": len(group)},
                        comparison={"population_count": len(attributions)},
                    )
                )
                if classification == "NO_ACTION":
                    self.metrics["no_action_findings"] += 1
                if classification == "RESTRICTED":
                    self.metrics["restriction_findings"] += 1
        return tuple(result)

    def _data_quality(self, snapshot: ResearchPerformanceSnapshot, attributions: tuple[ResearchOutcomeAttribution, ...]) -> tuple[ImprovementCandidate, ...]:
        group = tuple(item for item in attributions if item.trust_state not in {"UNKNOWN_TRUST_STATE", "TRUSTED", "TRUSTED_WITH_WARNINGS"})
        if len(group) < self.policy.minimum_evidence:
            return ()
        self.metrics["data_quality_findings"] += 1
        return (
            self._candidate(
                FindingType.DATA_QUALITY_FAILURE_PATTERN,
                FindingDomain.DATA,
                group,
                snapshot,
                "Data-quality/trust states recur in P48 outcome attributions.",
                "DataQualityFailure != StrategyDegradation; review sources and trust lineage before strategy conclusions.",
                Recommendation.REVIEW_DATA_SOURCE,
                self._strength(group, Decimal(len(group)) / Decimal(max(1, len(attributions)))),
                effect=Decimal(len(group)),
                affected={"trust_states": sorted({item.trust_state for item in group})},
                comparison={"population_count": len(attributions)},
            ),
        )

    def _portfolio(self, snapshot: ResearchPerformanceSnapshot, attributions: tuple[ResearchOutcomeAttribution, ...]) -> tuple[ImprovementCandidate, ...]:
        group = tuple(item for item in attributions if item.portfolio_state not in {"UNKNOWN_PORTFOLIO_STATE", "ACCEPTABLE"})
        if len(group) < self.policy.minimum_evidence:
            return ()
        self.metrics["portfolio_findings"] += 1
        return (
            self._candidate(
                FindingType.PORTFOLIO_RESTRICTION_PATTERN,
                FindingDomain.PORTFOLIO,
                group,
                snapshot,
                "Portfolio interaction states recur in outcome attributions.",
                "This is a research portfolio interaction hypothesis, not capital allocation.",
                Recommendation.REVIEW_PORTFOLIO_RULE,
                self._strength(group, Decimal(len(group)) / Decimal(max(1, len(attributions)))),
                effect=Decimal(len(group)),
                affected={"portfolio_states": sorted({item.portfolio_state for item in group})},
                comparison={"population_count": len(attributions)},
            ),
        )

    def _instability(self, snapshot: ResearchPerformanceSnapshot, attributions: tuple[ResearchOutcomeAttribution, ...]) -> tuple[ImprovementCandidate, ...]:
        values = _changes(attributions)
        if len(values) < self.policy.minimum_evidence:
            return ()
        spread = _q(max(values) - min(values))
        if spread < self.policy.instability_threshold:
            return ()
        supporting = tuple(item for item in attributions if (item.normalized_research_change or Decimal("0")) < Decimal("0"))
        contradicting = tuple(item for item in attributions if (item.normalized_research_change or Decimal("0")) > Decimal("0"))
        self.metrics["contradictory_evidence_count"] += int(bool(supporting and contradicting))
        return (
            self._candidate(
                FindingType.OUTCOME_INSTABILITY,
                FindingDomain.OUTCOME_ANALYTICS,
                attributions,
                snapshot,
                "Research outcomes show high dispersion across the analyzed evidence population.",
                "Contradictory evidence is surfaced separately; this is discovery evidence, not validation.",
                Recommendation.INVESTIGATE,
                self._strength(attributions, spread, contradictory=bool(supporting and contradicting)),
                effect=spread,
                affected={"spread": str(spread)},
                comparison={"minimum": str(min(values)), "maximum": str(max(values))},
                supporting=supporting,
                contradicting=contradicting,
            ),
        )

    def _candidate(
        self,
        finding_type: FindingType,
        domain: FindingDomain,
        evidence: Iterable[ResearchOutcomeAttribution],
        snapshot: ResearchPerformanceSnapshot,
        summary: str,
        detail: str,
        recommendation: Recommendation,
        strength: EvidenceStrength,
        *,
        effect: Decimal | None,
        affected: Mapping[str, Any] | None = None,
        comparison: Mapping[str, Any] | None = None,
        status: CandidateStatus | None = None,
        warnings: tuple[str, ...] = (),
        supporting: Iterable[ResearchOutcomeAttribution] | None = None,
        contradicting: Iterable[ResearchOutcomeAttribution] | None = None,
        exploratory: bool = False,
    ) -> ImprovementCandidate:
        items = tuple(sorted(_dedupe_attributions(tuple(evidence)), key=lambda item: item.attribution_id))
        support = tuple(sorted(_dedupe_attributions(tuple(supporting or items)), key=lambda item: item.attribution_id))
        contradiction = tuple(sorted(_dedupe_attributions(tuple(contradicting or ())), key=lambda item: item.attribution_id))
        refs = tuple(item.attribution_id for item in items)
        p47_refs = tuple(sorted({item.evidence_record_id for item in items}))
        windows = tuple(sorted({item.outcome_window_id for item in items}))
        affected_payload = dict(affected or {})
        comparison_payload = dict(comparison or {})
        if exploratory and strength is EvidenceStrength.STRONG:
            strength = EvidenceStrength.MODERATE
        if exploratory and strength is EvidenceStrength.MODERATE:
            strength = EvidenceStrength.WEAK
        priority, priority_reasons = self._priority(domain, strength, finding_type)
        hypothesis = {
            "target_component": affected_payload.get("strategy_id") or finding_type.value,
            "target_version": affected_payload.get("strategy_version") or "EVIDENCE_DEFINED",
            "affected_condition": affected_payload,
            "observed_finding": summary,
            "research_question": _hypothesis_text(finding_type, affected_payload, comparison_payload),
            "measurable_validation_criterion": "Prompt 50 controlled validation must reproduce the finding under predefined cohorts without weakening safety or bias controls.",
            "automatic_change": False,
            "validation_required": True,
        }
        content = {
            "finding_type": finding_type.value,
            "domain": domain.value,
            "refs": refs,
            "supporting": tuple(item.attribution_id for item in support),
            "contradicting": tuple(item.attribution_id for item in contradiction),
            "snapshot": snapshot.snapshot_id,
            "policy": self.policy.policy_identity,
            "configuration": self.configuration_identity,
            "affected": affected_payload,
            "comparison": comparison_payload,
            "effect": effect,
            "strength": strength.value,
            "exploratory": exploratory,
        }
        fingerprint = _sha256_json(content)
        candidate = ImprovementCandidate(
            deterministic_id("p49_improvement_candidate", fingerprint),
            IMPROVEMENT_CANDIDATE_SCHEMA_VERSION,
            improvement_candidate_schema_identity(),
            domain.value,
            str(affected_payload.get("strategy_id") or affected_payload.get("classification") or finding_type.value),
            str(affected_payload.get("strategy_version") or "EVIDENCE_DEFINED"),
            finding_type.value,
            domain.value,
            summary,
            detail,
            "ENGINEERING_RELIABILITY_FINDING" if domain in {FindingDomain.DATA, FindingDomain.EVIDENCE, FindingDomain.RELIABILITY} else "RESEARCH_BEHAVIOR_FINDING",
            refs,
            tuple(item.attribution_id for item in support),
            tuple(item.attribution_id for item in contradiction),
            len(refs),
            len(windows),
            affected_payload,
            comparison_payload,
            tuple(snapshot.source_evidence_fingerprints),
            refs,
            (snapshot.snapshot_id,),
            p47_refs,
            strength.value,
            "DESCRIPTIVE_NOT_PROBABILITY",
            "NEGATIVE" if effect is not None and effect < 0 else "POSITIVE" if effect is not None and effect > 0 else "NEUTRAL_OR_GAP",
            effect,
            "STABLE" if finding_type is not FindingType.OUTCOME_INSTABILITY else "UNSTABLE",
            (
                "DiscoveryEvidence != ValidationEvidence",
                "Pattern != RootCause",
                "Recommendation != ConfigurationMutation",
            ),
            _confounders(items),
            tuple(dict.fromkeys(warnings + (("P49_CONTRADICTORY_EVIDENCE_PRESENT",) if contradiction else ()))),
            recommendation.value,
            hypothesis,
            priority,
            priority_reasons,
            False,
            True,
            (status or CandidateStatus.VALIDATION_REQUIRED).value,
            None,
            self.configuration_identity,
            self.policy.policy_identity,
            snapshot.as_of,
            snapshot.as_of,
            exploratory,
            fingerprint,
        )
        self._record("improvement_candidate_identified", {"candidate_id": candidate.candidate_id, "finding_type": finding_type.value})
        if contradiction:
            self._record("contradictory_evidence_detected", {"candidate_id": candidate.candidate_id, "count": len(contradiction)})
        return candidate

    def _strength(
        self,
        evidence: Iterable[ResearchOutcomeAttribution],
        magnitude: Decimal,
        *,
        contradictory: bool = False,
    ) -> EvidenceStrength:
        unique = _dedupe_attributions(tuple(evidence))
        count = len(unique)
        if count < self.policy.minimum_evidence:
            return EvidenceStrength.INSUFFICIENT
        if magnitude < self.policy.practical_significance_threshold:
            return EvidenceStrength.WEAK
        if count >= self.policy.strong_evidence and not contradictory:
            return EvidenceStrength.STRONG
        if count >= self.policy.moderate_evidence:
            return EvidenceStrength.MODERATE
        return EvidenceStrength.WEAK

    def _priority(
        self,
        domain: FindingDomain,
        strength: EvidenceStrength,
        finding_type: FindingType,
    ) -> tuple[str, tuple[str, ...]]:
        reasons = []
        score = 0
        if domain.value in self.policy.safety_first_domains:
            score += 2
            reasons.append("P49_SAFETY_FIRST_DOMAIN")
        if finding_type in {FindingType.DATA_QUALITY_FAILURE_PATTERN, FindingType.REPEATED_FAILURE_CLUSTER, FindingType.PROTECTION_INTERVENTION_PATTERN}:
            score += 2
            reasons.append("P49_RELIABILITY_OR_SAFETY_RELEVANT")
        score += {EvidenceStrength.INSUFFICIENT: 0, EvidenceStrength.WEAK: 1, EvidenceStrength.MODERATE: 2, EvidenceStrength.STRONG: 3}[strength]
        if score >= 5:
            return "HIGH", tuple(reasons)
        if score >= 3:
            return "MEDIUM", tuple(reasons)
        return "LOW", tuple(reasons or ("P49_RESEARCH_DISCOVERY_PRIORITY",))

    def _clusters(
        self,
        candidates: tuple[ImprovementCandidate, ...],
        attributions: tuple[ResearchOutcomeAttribution, ...],
        as_of: datetime,
    ) -> tuple[ResearchFailureCluster, ...]:
        result = []
        groups: dict[str, list[ImprovementCandidate]] = defaultdict(list)
        for candidate in candidates:
            groups[candidate.finding_type].append(candidate)
        by_attr = {item.attribution_id: item for item in attributions}
        for finding_type, items in sorted(groups.items()):
            evidence_ids = tuple(sorted({ref for candidate in items for ref in candidate.evidence_refs}))
            if len(evidence_ids) < self.policy.minimum_evidence:
                continue
            members = tuple(by_attr[item] for item in evidence_ids if item in by_attr)
            payload = {
                "finding_type": finding_type,
                "members": evidence_ids,
                "policy": self.policy.policy_identity,
            }
            fingerprint = _sha256_json(payload)
            cluster = ResearchFailureCluster(
                deterministic_id("p49_failure_cluster", fingerprint),
                RESEARCH_FAILURE_CLUSTER_SCHEMA_VERSION,
                research_failure_cluster_schema_identity(),
                finding_type,
                evidence_ids,
                tuple(sorted({candidate.component_id for candidate in items})),
                tuple(sorted({item.strategy_id for item in members})),
                tuple(sorted({item.regime_at_decision for item in members})),
                tuple(sorted({item.session_at_decision for item in members})),
                len(evidence_ids),
                (
                    min((item.historical_knowledge_cutoff for item in members), default=None),
                    max((item.historical_knowledge_cutoff for item in members), default=None),
                ),
                _count_mapping(candidate.finding_type for candidate in items),
                self._strength(members, Decimal(len(members)) / Decimal(max(1, len(attributions)))).value,
                fingerprint,
            )
            result.append(cluster)
            self._record("failure_cluster_identified", {"cluster_id": cluster.cluster_id, "finding_type": finding_type})
        return tuple(result)

    def _snapshot(
        self,
        candidates: tuple[ImprovementCandidate, ...],
        clusters: tuple[ResearchFailureCluster, ...],
        source: ResearchPerformanceSnapshot,
        as_of: datetime,
        source_p47_ledger_range: tuple[int, int] | None,
    ) -> ResearchImprovementSnapshot:
        payload = {
            "as_of": as_of,
            "candidates": tuple(item.candidate_id for item in candidates),
            "clusters": tuple(item.cluster_id for item in clusters),
            "source": source.snapshot_id,
            "policy": self.policy.policy_identity,
            "configuration": self.configuration_identity,
        }
        fingerprint = _sha256_json(payload)
        snapshot = ResearchImprovementSnapshot(
            deterministic_id("p49_research_improvement_snapshot", fingerprint),
            RESEARCH_IMPROVEMENT_SNAPSHOT_SCHEMA_VERSION,
            research_improvement_snapshot_schema_identity(),
            as_of,
            (source.snapshot_id,),
            source_p47_ledger_range,
            tuple(item.candidate_id for item in candidates),
            len(candidates),
            _count_mapping(item.finding_type for item in candidates),
            _count_mapping(item.finding_domain for item in candidates),
            _count_mapping(item.evidence_strength for item in candidates),
            _count_mapping(item.investigation_priority for item in candidates),
            tuple(item.candidate_id for item in candidates if item.finding_domain == FindingDomain.STRATEGY.value),
            tuple(item.candidate_id for item in candidates if item.finding_type == FindingType.REGIME_SENSITIVITY.value),
            tuple(item.candidate_id for item in candidates if item.finding_type == FindingType.SESSION_SENSITIVITY.value),
            tuple(item.candidate_id for item in candidates if item.finding_domain == FindingDomain.DATA.value),
            tuple(item.candidate_id for item in candidates if item.finding_type == FindingType.NO_ACTION_PATTERN.value),
            tuple(item.candidate_id for item in candidates if item.finding_type == FindingType.RESTRICTION_PATTERN.value),
            tuple(item.candidate_id for item in candidates if item.finding_domain == FindingDomain.PORTFOLIO.value),
            tuple(item.candidate_id for item in candidates if item.finding_domain == FindingDomain.RELIABILITY.value),
            sum(1 for item in candidates if item.evidence_strength == EvidenceStrength.INSUFFICIENT.value),
            sum(1 for item in candidates if item.contradicting_evidence_refs),
            tuple(item.cluster_id for item in clusters),
            tuple(sorted({warning for item in candidates for warning in item.warnings})),
            (
                "ResearchFinding != ConfirmedSoftwareDefect",
                "DiscoveryEvidence != ValidationEvidence",
                "HighInvestigationPriority != PermissionToModify",
            ),
            self.policy.policy_identity,
            self.configuration_identity,
            "P49_RESEARCH_IMPROVEMENT_INTELLIGENCE",
            fingerprint,
        )
        self._record("improvement_snapshot_published", {"snapshot_id": snapshot.snapshot_id, "candidates": len(candidates)})
        return snapshot

    @staticmethod
    def _trim(items: OrderedDict[str, Any], maximum: int) -> None:
        while len(items) > maximum:
            items.popitem(last=False)

    def _record(self, event: str, payload: Mapping[str, Any]) -> None:
        if self.audit is not None:
            self.audit.record(event, dict(payload))


class ResearchImprovementComponent:
    def __init__(self, component_id: str, holder: dict[str, ResearchImprovementRuntime]) -> None:
        self.component_id = component_id
        self.runtime: ResearchImprovementRuntime | None = None
        self._holder = holder

    def initialize_component(self, context: Any) -> None:
        if self.runtime is None:
            if "runtime" in self._holder:
                self.runtime = self._holder["runtime"]
            else:
                self.runtime = ResearchImprovementRuntime(clock=context.services["clock"], audit=context.services["audit"])
                self._holder["runtime"] = self.runtime
        self.runtime.initialize_component(context)

    def component_ready(self, context: Any) -> bool:
        return self.runtime.component_ready(context) if self.runtime is not None else False

    def component_health(self, context: Any) -> HealthStatus:
        return self.runtime.component_health(context) if self.runtime is not None else HealthStatus.UNKNOWN

    def diagnostics(self) -> dict[str, Any]:
        payload = self.runtime.diagnostics() if self.runtime is not None else {}
        payload["component_id"] = self.component_id
        return payload


def research_improvement_component_registrations() -> tuple[tuple[ComponentMetadata, ResearchImprovementComponent], ...]:
    holder: dict[str, ResearchImprovementRuntime] = {}
    definitions = (
        ("improvement_evidence_validator", ("research_performance_snapshot",)),
        ("research_pattern_analysis", ("improvement_evidence_validator",)),
        ("research_stability_analysis", ("research_pattern_analysis",)),
        ("research_failure_clustering", ("research_stability_analysis",)),
        ("improvement_hypothesis_generation", ("research_failure_clustering",)),
        ("research_improvement_snapshot", ("improvement_hypothesis_generation",)),
    )
    capabilities = ComponentCapabilities(lifecycle=True, persistence=True, recovery=True, health=True, diagnostics=True, activation=True)
    return tuple(
        (
            ComponentMetadata(component_id, ComponentType.RESEARCH, RESEARCH_IMPROVEMENT_RUNTIME_VERSION, True, dependencies, capabilities),
            ResearchImprovementComponent(component_id, holder),
        )
        for component_id, dependencies in definitions
    )


def research_improvement_components_from_inventory(inventory: tuple[Mapping[str, Any], ...]) -> dict[str, dict[str, Any]]:
    ids = {
        "improvement_evidence_validator",
        "research_pattern_analysis",
        "research_stability_analysis",
        "research_failure_clustering",
        "improvement_hypothesis_generation",
        "research_improvement_snapshot",
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


def improvement_candidate_schema_identity() -> str:
    return _sha256_json(
        {
            "schema": "p49_improvement_candidate",
            "version": IMPROVEMENT_CANDIDATE_SCHEMA_VERSION,
            "fields": tuple(ImprovementCandidate.__dataclass_fields__),
            "p47": research_decision_evidence_record_schema_identity(),
            "p48": research_outcome_attribution_schema_identity(),
        }
    )


def research_failure_cluster_schema_identity() -> str:
    return _sha256_json(
        {
            "schema": "p49_research_failure_cluster",
            "version": RESEARCH_FAILURE_CLUSTER_SCHEMA_VERSION,
            "fields": tuple(ResearchFailureCluster.__dataclass_fields__),
            "candidate": improvement_candidate_schema_identity(),
        }
    )


def research_improvement_snapshot_schema_identity() -> str:
    return _sha256_json(
        {
            "schema": "p49_research_improvement_snapshot",
            "version": RESEARCH_IMPROVEMENT_SNAPSHOT_SCHEMA_VERSION,
            "fields": tuple(ResearchImprovementSnapshot.__dataclass_fields__),
            "candidate": improvement_candidate_schema_identity(),
            "cluster": research_failure_cluster_schema_identity(),
        }
    )


def research_improvement_policy_identity() -> str:
    return ResearchImprovementPolicy.current().policy_identity


def _dedupe_attributions(items: tuple[ResearchOutcomeAttribution, ...]) -> tuple[ResearchOutcomeAttribution, ...]:
    seen: OrderedDict[str, ResearchOutcomeAttribution] = OrderedDict()
    for item in items:
        seen.setdefault(item.attribution_id, item)
    return tuple(seen.values())


def _changes(items: Iterable[ResearchOutcomeAttribution]) -> tuple[Decimal, ...]:
    return tuple(item.normalized_research_change for item in items if item.normalized_research_change is not None)


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    return _q(sum(values, Decimal("0")) / Decimal(len(values))) if values else None


def _q(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.00000001"))


def _group(items: tuple[ResearchOutcomeAttribution, ...], key_fn: Any) -> dict[tuple[str, ...], tuple[ResearchOutcomeAttribution, ...]]:
    grouped: dict[tuple[str, ...], list[ResearchOutcomeAttribution]] = defaultdict(list)
    for item in items:
        grouped[tuple(str(value) for value in key_fn(item))].append(item)
    return {key: tuple(value) for key, value in grouped.items()}


def _confounders(items: tuple[ResearchOutcomeAttribution, ...]) -> tuple[str, ...]:
    values = []
    if len({item.future_dataset_ids for item in items}) > 1:
        values.append("P49_MULTI_DATASET_CONFOUNDER")
    if len({item.configuration_identity for item in items}) > 1:
        values.append("P49_CONFIGURATION_VARIANT_CONFOUNDER")
    if any(item.decision_classification in {"FAILED", "REJECTED"} for item in items):
        values.append("P49_FAILURE_POPULATION_DISTINCT")
    return tuple(values)


def _hypothesis_text(finding_type: FindingType, affected: Mapping[str, Any], comparison: Mapping[str, Any]) -> str:
    return (
        f"Investigate whether {finding_type.value} observed under {dict(affected)} persists "
        f"against predefined validation cohorts compared with {dict(comparison)} without weakening safety, evidence, or bias controls."
    )


def _count_mapping(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items()))


def _snapshot_stub(snapshot: ResearchImprovementSnapshot) -> ResearchPerformanceSnapshot:
    return ResearchPerformanceSnapshot(
        snapshot.source_p48_snapshot_ids[0],
        "1.0",
        research_performance_snapshot_schema_identity(),
        snapshot.analysis_as_of,
        "P49_REBUILD_STUB",
        (),
        0,
        0,
        0,
        0,
        0,
        {},
        (),
        {},
        {},
        {},
        {},
        {},
        {},
        {},
        {},
        {},
        "P49_REBUILD",
        (),
        (),
        snapshot.source_p47_ledger_range,
        (),
        snapshot.configuration_identity,
        research_outcome_policy_identity(),
        "P49_REBUILD_STUB",
        snapshot.source_p48_snapshot_ids[0],
    )


def canonical_json(value: Any) -> str:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {field: _jsonable(getattr(value, field)) for field in value.__dataclass_fields__}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return [_jsonable(item) for item in sorted(value, key=str)]
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, Path):
        return value.as_posix()
    return value
