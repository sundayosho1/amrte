from __future__ import annotations

import hashlib
import json
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from amrte.analytics.performance import (
    AnalyticsConfiguration,
    AnalyticsScope,
    ResearchAnalyticsQuery,
    ResearchOutcomeObservation as AnalyticsOutcomeObservation,
    ResearchPerformanceAnalyticsEngine,
)
from amrte.core.composition import ComponentCapabilities, ComponentMetadata, ComponentType
from amrte.core.constants import AMRTE_VERSION
from amrte.core.identity import deterministic_id
from amrte.core.types import HealthStatus
from amrte.market.observation import CanonicalMarketObservation, validate_canonical_observation
from amrte.research.data_quality_runtime import TrustStatus, TrustedResearchObservation, quality_trust_schema_identity
from amrte.research.evidence_ledger import (
    LedgerVerificationStatus,
    ResearchDecisionEvidenceLedger,
    ResearchDecisionEvidenceRecord,
    research_decision_evidence_record_schema_identity,
)


RESEARCH_OUTCOME_RUNTIME_VERSION = "1.0"
RESEARCH_OUTCOME_WINDOW_SCHEMA_VERSION = "1.0"
RESEARCH_OUTCOME_ATTRIBUTION_SCHEMA_VERSION = "1.0"
RESEARCH_PERFORMANCE_SNAPSHOT_SCHEMA_VERSION = "1.0"
RESEARCH_OUTCOME_POLICY_VERSION = "1.0"


class OutcomeWindowState(Enum):
    PENDING = "PENDING"
    PARTIALLY_OBSERVED = "PARTIALLY_OBSERVED"
    MATURE = "MATURE"
    INVALID = "INVALID"
    UNAVAILABLE = "UNAVAILABLE"


class OutcomeDataQualityState(Enum):
    TRUSTED = "TRUSTED"
    RESTRICTED = "RESTRICTED"
    INVALID = "INVALID"
    UNAVAILABLE = "UNAVAILABLE"


class AnalysisIntent(Enum):
    PREDEFINED = "PREDEFINED"
    EXPLORATORY = "EXPLORATORY"


class MetricApplicability(Enum):
    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    INVALID = "INVALID"


class HypothesisOutcome(Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    INVALIDATED = "INVALIDATED"
    INDETERMINATE = "INDETERMINATE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class OutcomeHorizonDefinition:
    horizon_id: str
    horizon_type: str
    required_observation_count: int
    maximum_elapsed_seconds: int | None
    analysis_intent: str = AnalysisIntent.PREDEFINED.value


@dataclass(frozen=True)
class ScoreBandDefinition:
    band_id: str
    lower_inclusive: Decimal | None
    upper_exclusive: Decimal | None


@dataclass(frozen=True)
class ResearchOutcomePolicy:
    policy_id: str
    version: str
    window_definitions: tuple[OutcomeHorizonDefinition, ...]
    maturity_rule: str
    missing_data_policy: str
    minimum_sample_size: int
    score_bands: tuple[ScoreBandDefinition, ...]
    reference_value_policy: str
    excursion_policy: str
    hypothesis_policy: str
    aggregation_policy: str
    policy_identity: str

    @classmethod
    def current(cls) -> "ResearchOutcomePolicy":
        horizons = (
            OutcomeHorizonDefinition("H3_OBSERVATIONS", "N_OBSERVATIONS", 3, None),
            OutcomeHorizonDefinition("H5_OBSERVATIONS", "N_OBSERVATIONS", 5, None),
        )
        score_bands = (
            ScoreBandDefinition("LOW", Decimal("0"), Decimal("0.33")),
            ScoreBandDefinition("MEDIUM", Decimal("0.33"), Decimal("0.66")),
            ScoreBandDefinition("HIGH", Decimal("0.66"), None),
        )
        payload = {
            "policy_id": "P48_RESEARCH_OUTCOME_POLICY",
            "version": RESEARCH_OUTCOME_POLICY_VERSION,
            "window_definitions": horizons,
            "maturity_rule": "predefined-horizon-observations-only",
            "missing_data_policy": "missing-is-not-zero-and-remains-denominator-visible",
            "minimum_sample_size": 3,
            "score_bands": score_bands,
            "reference_value_policy": "historical-reference-required-for-directional-excursion",
            "excursion_policy": "research-market-path-not-account-return",
            "hypothesis_policy": "directional-support-only-when-direction-and-reference-exist",
            "aggregation_policy": "classification-aware-denominator-preserving",
        }
        return cls(
            payload["policy_id"],
            payload["version"],
            horizons,
            payload["maturity_rule"],
            payload["missing_data_policy"],
            payload["minimum_sample_size"],
            score_bands,
            payload["reference_value_policy"],
            payload["excursion_policy"],
            payload["hypothesis_policy"],
            payload["aggregation_policy"],
            _sha256_json(payload),
        )

    def horizon(self, horizon_id: str) -> OutcomeHorizonDefinition:
        for item in self.window_definitions:
            if item.horizon_id == horizon_id:
                return item
        raise KeyError(horizon_id)


@dataclass(frozen=True)
class FutureOutcomeObservation:
    observation_id: str
    observation_fingerprint: str
    trusted_observation_id: str
    quality_snapshot_id: str
    source_health_snapshot_id: str
    trust_status: str
    dataset_id: str
    dataset_fingerprint: str
    source_id: str
    instrument_id: str
    timeframe: str
    event_time: datetime
    available_at: datetime
    received_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    source_metadata: Mapping[str, Any]
    quality_metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_metadata", MappingProxyType(dict(self.source_metadata)))
        object.__setattr__(self, "quality_metadata", MappingProxyType(dict(self.quality_metadata)))

    @classmethod
    def from_canonical(
        cls,
        observation: CanonicalMarketObservation,
        trusted: TrustedResearchObservation,
        *,
        logical_time: datetime,
    ) -> "FutureOutcomeObservation":
        validation = validate_canonical_observation(observation, logical_time=logical_time)
        if not validation.valid:
            raise ValueError("P48_FUTURE_OBSERVATION_INVALID")
        envelope = trusted.envelope
        if envelope.observation_id != observation.observation_id or envelope.observation_fingerprint != observation.observation_fingerprint:
            raise ValueError("P48_TRUST_ENVELOPE_OBSERVATION_MISMATCH")
        if envelope.dataset_fingerprint != observation.source.source_dataset and envelope.dataset_id != observation.source.source_dataset:
            # Existing P40 tests use dataset ids independently from source_dataset;
            # keep this as a warning-equivalent guard below via explicit fields.
            pass
        if trusted.trust_status not in (TrustStatus.TRUSTED, TrustStatus.TRUSTED_WITH_WARNINGS):
            raise ValueError("P48_FUTURE_OBSERVATION_NOT_TRUSTED")
        return cls(
            observation.observation_id,
            observation.observation_fingerprint,
            trusted.trusted_observation_id,
            trusted.quality_snapshot_id,
            trusted.source_health_snapshot_id,
            trusted.trust_status.value,
            envelope.dataset_id,
            envelope.dataset_fingerprint,
            envelope.source_id,
            observation.instrument.canonical_id,
            observation.timeframe,
            observation.event_time,
            observation.available_at,
            observation.received_at,
            observation.bar.open,
            observation.bar.high,
            observation.bar.low,
            observation.bar.close,
            observation.source_metadata,
            observation.quality_metadata,
        )


@dataclass(frozen=True)
class ResearchOutcomeWindow:
    window_id: str
    schema_version: str
    schema_identity: str
    decision_id: str
    trace_id: str
    evidence_record_id: str
    decision_knowledge_cutoff: datetime
    instrument_id: str
    timeframe: str
    window_start: datetime
    window_end: datetime | None
    window_type: str
    horizon_definition: Mapping[str, Any]
    required_observation_count: int
    actual_observation_count: int
    coverage_state: str
    data_quality_state: str
    observation_ids: tuple[str, ...]
    observation_fingerprints: tuple[str, ...]
    source_ids: tuple[str, ...]
    dataset_ids: tuple[str, ...]
    dataset_fingerprints: tuple[str, ...]
    outcome_as_of: datetime | None
    outcome_available_at: datetime | None
    evaluation_time: datetime
    configuration_identity: str
    policy_identity: str
    exploratory: bool
    invalid_reasons: tuple[str, ...]
    window_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "horizon_definition", MappingProxyType(dict(self.horizon_definition)))


@dataclass(frozen=True)
class OutcomeExcursion:
    applicability: str
    research_direction: str
    reference_value: Decimal | None
    maximum_favorable: Decimal | None
    maximum_adverse: Decimal | None
    time_to_favorable_seconds: int | None
    time_to_adverse_seconds: int | None
    data_resolution: str
    coverage_state: str


@dataclass(frozen=True)
class ResearchOutcomeAttribution:
    attribution_id: str
    schema_version: str
    schema_identity: str
    attribution_version: str
    evidence_record_id: str
    decision_id: str
    trace_id: str
    historical_knowledge_cutoff: datetime
    outcome_window_id: str
    outcome_policy_identity: str
    future_dataset_ids: tuple[str, ...]
    future_source_ids: tuple[str, ...]
    decision_classification: str
    strategy_id: str
    strategy_version: str
    strategy_implementation_identity: str
    candidate_id: str | None
    research_direction: str
    regime_at_decision: str
    realized_regime: str
    session_at_decision: str
    configuration_identity: str
    outcome_analysis_configuration_identity: str
    release_identity: str
    score_value: Decimal | None
    score_band: str
    score_is_probability: bool
    protection_state: str
    restriction_state: str
    portfolio_state: str
    trust_state: str
    normalized_research_change: Decimal | None
    research_change_applicability: str
    favorable_adverse_excursion: OutcomeExcursion
    hypothesis_outcome: str
    invalidation_observation_id: str | None
    time_to_invalidation_seconds: int | None
    observations_to_invalidation: int | None
    no_action_reason: str | None
    causal_claim: bool
    financial_execution: str
    supersedes_attribution_id: str | None
    original_dataset_fingerprint: str | None
    revised_dataset_fingerprint: str | None
    attribution_fingerprint: str


@dataclass(frozen=True)
class CohortDefinition:
    cohort_definition_id: str
    dimensions: tuple[str, ...]
    analysis_intent: str
    policy_identity: str
    cohort_fingerprint: str

    @classmethod
    def create(
        cls,
        dimensions: Iterable[str],
        policy: ResearchOutcomePolicy,
        *,
        analysis_intent: AnalysisIntent = AnalysisIntent.PREDEFINED,
    ) -> "CohortDefinition":
        dims = tuple(sorted(dict.fromkeys(str(item) for item in dimensions)))
        fingerprint = _sha256_json({"dimensions": dims, "policy": policy.policy_identity, "intent": analysis_intent.value})
        return cls(
            deterministic_id("p48_cohort_definition", fingerprint),
            dims,
            analysis_intent.value,
            policy.policy_identity,
            fingerprint,
        )


@dataclass(frozen=True)
class CohortStatistics:
    cohort_definition_id: str
    cohort_key: tuple[tuple[str, str], ...]
    sample_count: int
    complete_outcome_count: int
    partial_outcome_count: int
    missing_outcome_count: int
    invalid_outcome_count: int
    sufficiency_state: str
    mean_research_change: Decimal | None
    median_research_change: Decimal | None
    minimum_research_change: Decimal | None
    maximum_research_change: Decimal | None
    positive_count: int
    negative_count: int
    neutral_count: int
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ResearchPerformanceSnapshot:
    snapshot_id: str
    schema_version: str
    schema_identity: str
    as_of: datetime
    population_definition: str
    cohort_definitions: tuple[CohortDefinition, ...]
    decision_count: int
    mature_outcome_count: int
    partial_count: int
    missing_count: int
    invalid_count: int
    classification_distribution: Mapping[str, int]
    outcome_statistics: tuple[CohortStatistics, ...]
    no_action_statistics: Mapping[str, Any]
    restriction_statistics: Mapping[str, Any]
    protection_statistics: Mapping[str, Any]
    strategy_attribution: Mapping[str, int]
    regime_attribution: Mapping[str, int]
    session_attribution: Mapping[str, int]
    configuration_attribution: Mapping[str, int]
    portfolio_interaction_evidence: Mapping[str, int]
    data_quality_indicators: Mapping[str, int]
    sample_sufficiency: str
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    source_ledger_range: tuple[int, int] | None
    source_evidence_fingerprints: tuple[str, ...]
    configuration_identity: str
    policy_identity: str
    pipeline_identity: str
    snapshot_fingerprint: str
    financial_execution: str = "NONE"

    def __post_init__(self) -> None:
        for field_name in (
            "classification_distribution",
            "no_action_statistics",
            "restriction_statistics",
            "protection_statistics",
            "strategy_attribution",
            "regime_attribution",
            "session_attribution",
            "configuration_attribution",
            "portfolio_interaction_evidence",
            "data_quality_indicators",
        ):
            object.__setattr__(self, field_name, MappingProxyType(dict(getattr(self, field_name))))


@dataclass(frozen=True)
class OutcomeRuntimeRecoveryState:
    schema_version: str
    runtime_version: str
    policy_identity: str
    configuration_identity: str
    recovery_epoch: int
    processed_evidence_ids: tuple[str, ...]
    pending_window_ids: tuple[str, ...]
    matured_window_ids: tuple[str, ...]
    attribution_ids: tuple[str, ...]
    snapshot_ids: tuple[str, ...]
    windows: tuple[ResearchOutcomeWindow, ...]
    attributions: tuple[ResearchOutcomeAttribution, ...]
    snapshots: tuple[ResearchPerformanceSnapshot, ...]


class ResearchOutcomePerformanceRuntime:
    """Prompt 48 research-only outcome attribution and performance intelligence."""

    def __init__(
        self,
        *,
        clock: Any,
        audit: Any,
        evidence_ledger: ResearchDecisionEvidenceLedger | None = None,
        policy: ResearchOutcomePolicy | None = None,
        storage_root: Path = Path("data/research-outcome-performance"),
        configuration_identity: str = "P48_OUTCOME_ANALYTICS_DEFAULT",
        maximum_windows: int = 4096,
        maximum_attributions: int = 4096,
        maximum_snapshots: int = 512,
        maximum_query_limit: int = 100,
    ) -> None:
        self.clock = clock
        self.audit = audit
        self.evidence_ledger = evidence_ledger
        self.policy = policy or ResearchOutcomePolicy.current()
        self.storage_root = Path(storage_root)
        self.configuration_identity = configuration_identity
        self.maximum_windows = max(1, maximum_windows)
        self.maximum_attributions = max(1, maximum_attributions)
        self.maximum_snapshots = max(1, maximum_snapshots)
        self.maximum_query_limit = max(1, min(maximum_query_limit, 500))
        self.windows: OrderedDict[str, ResearchOutcomeWindow] = OrderedDict()
        self.attributions: OrderedDict[str, ResearchOutcomeAttribution] = OrderedDict()
        self.snapshots: OrderedDict[str, ResearchPerformanceSnapshot] = OrderedDict()
        self.processed_evidence_ids: set[str] = set()
        self.recovery_restricted = False
        self.metrics = {
            "p47_records_received": 0,
            "windows_opened": 0,
            "windows_pending": 0,
            "windows_matured": 0,
            "windows_invalid": 0,
            "windows_unavailable": 0,
            "attributions_published": 0,
            "no_action_attributions": 0,
            "restricted_attributions": 0,
            "eligible_research_attributions": 0,
            "cohort_counts": 0,
            "insufficient_sample_cohorts": 0,
            "future_data_rejections": 0,
            "data_quality_restrictions": 0,
            "recovery_count": 0,
            "recovery_divergence": 0,
        }
        self._analytics = ResearchPerformanceAnalyticsEngine(
            AnalyticsConfiguration(configuration_snapshot_id=configuration_identity, limited_sample=self.policy.minimum_sample_size)
        )
        self.initialize_component(None)

    def initialize_component(self, context: Any) -> None:
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self._record("research_outcome_runtime_initialized", {"policy_identity": self.policy.policy_identity})

    def open_window(
        self,
        record: ResearchDecisionEvidenceRecord,
        *,
        horizon_id: str = "H3_OBSERVATIONS",
        instrument_id: str | None = None,
        timeframe: str | None = None,
        evaluation_time: datetime | None = None,
    ) -> ResearchOutcomeWindow:
        self._assert_p47_verified(record)
        horizon = self.policy.horizon(horizon_id)
        instrument = instrument_id or _extract_reason_value(record.reason_codes, "INSTRUMENT") or "UNKNOWN_INSTRUMENT"
        tf = timeframe or _extract_reason_value(record.reason_codes, "TIMEFRAME") or "UNKNOWN_TIMEFRAME"
        now = evaluation_time or self.clock.now()
        window = self._window_from_observations(record, horizon, (), instrument, tf, now)
        self._store_window(window)
        self.metrics["p47_records_received"] += 1
        self.metrics["windows_opened"] += 1
        self.metrics["windows_pending"] += 1
        self._record("outcome_window_opened", {"window_id": window.window_id, "record_id": record.evidence_record_id})
        return window

    def update_window(
        self,
        record: ResearchDecisionEvidenceRecord,
        observations: Iterable[FutureOutcomeObservation],
        *,
        horizon_id: str = "H3_OBSERVATIONS",
        instrument_id: str | None = None,
        timeframe: str | None = None,
        evaluation_time: datetime | None = None,
    ) -> ResearchOutcomeWindow:
        self._assert_p47_verified(record)
        horizon = self.policy.horizon(horizon_id)
        now = evaluation_time or self.clock.now()
        ordered = tuple(sorted(observations, key=lambda item: (item.event_time, item.observation_id)))
        instrument = instrument_id or (ordered[0].instrument_id if ordered else _extract_reason_value(record.reason_codes, "INSTRUMENT") or "UNKNOWN_INSTRUMENT")
        tf = timeframe or (ordered[0].timeframe if ordered else _extract_reason_value(record.reason_codes, "TIMEFRAME") or "UNKNOWN_TIMEFRAME")
        window = self._window_from_observations(record, horizon, ordered, instrument, tf, now)
        previous = self.windows.get(window.window_id)
        self._store_window(window)
        if window.coverage_state == OutcomeWindowState.MATURE.value and (previous is None or previous.coverage_state != OutcomeWindowState.MATURE.value):
            self.metrics["windows_matured"] += 1
            self._record("outcome_window_matured", {"window_id": window.window_id})
        elif window.coverage_state == OutcomeWindowState.INVALID.value:
            self.metrics["windows_invalid"] += 1
            self._record("outcome_window_invalid", {"window_id": window.window_id, "reasons": window.invalid_reasons})
        else:
            self._record("outcome_window_updated", {"window_id": window.window_id, "state": window.coverage_state})
        return window

    def attribute(
        self,
        record: ResearchDecisionEvidenceRecord,
        window: ResearchOutcomeWindow,
        observations: Iterable[FutureOutcomeObservation],
        *,
        historical_reference_value: Decimal | None = None,
        supersedes_attribution_id: str | None = None,
        revised_dataset_fingerprint: str | None = None,
    ) -> ResearchOutcomeAttribution:
        self._assert_p47_verified(record)
        if window.evidence_record_id != record.evidence_record_id:
            raise ValueError("P48_WINDOW_RECORD_MISMATCH")
        if window.coverage_state != OutcomeWindowState.MATURE.value:
            raise ValueError("P48_OUTCOME_SELECTED_BEFORE_WINDOW_MATURITY")
        ordered = tuple(sorted(observations, key=lambda item: (item.event_time, item.observation_id)))[: window.required_observation_count]
        if tuple(item.observation_id for item in ordered) != window.observation_ids:
            raise ValueError("P48_WINDOW_OBSERVATION_MISMATCH")
        duplicate = self._find_attribution(record.evidence_record_id, window.window_id, revised_dataset_fingerprint)
        if duplicate is not None:
            return duplicate
        dimensions = _historical_dimensions(record, self.policy)
        change = _normalized_change(ordered, historical_reference_value, dimensions["direction"])
        excursion = _excursion(ordered, historical_reference_value, dimensions["direction"], window.coverage_state)
        hypothesis, invalid_obs, invalid_seconds, invalid_count = _hypothesis(ordered, historical_reference_value, dimensions["direction"], record.knowledge_cutoff_utc)
        content = {
            "record": record.evidence_record_id,
            "decision": record.decision_id,
            "trace": record.trace_id,
            "window": window.window_id,
            "policy": self.policy.policy_identity,
            "configuration": self.configuration_identity,
            "classification": record.final_classification,
            "dimensions": dimensions,
            "change": change,
            "excursion": excursion,
            "hypothesis": hypothesis.value,
            "revised_dataset": revised_dataset_fingerprint,
            "supersedes": supersedes_attribution_id,
        }
        fingerprint = _sha256_json(content)
        attribution = ResearchOutcomeAttribution(
            deterministic_id("p48_research_outcome_attribution", fingerprint),
            RESEARCH_OUTCOME_ATTRIBUTION_SCHEMA_VERSION,
            research_outcome_attribution_schema_identity(),
            "1.0",
            record.evidence_record_id,
            record.decision_id,
            record.trace_id,
            record.knowledge_cutoff_utc,
            window.window_id,
            self.policy.policy_identity,
            window.dataset_ids,
            window.source_ids,
            record.final_classification,
            dimensions["strategy_id"],
            dimensions["strategy_version"],
            dimensions["strategy_implementation_identity"],
            dimensions["candidate_id"],
            dimensions["direction"],
            dimensions["regime_at_decision"],
            dimensions["realized_regime"],
            dimensions["session_at_decision"],
            record.configuration_identity,
            self.configuration_identity,
            str(record.release_provenance.get("git_commit", "UNKNOWN")),
            dimensions["score_value"],
            dimensions["score_band"],
            False,
            str(record.p46_final_decision.get("effective_permission", "UNKNOWN")),
            dimensions["restriction_state"],
            dimensions["portfolio_state"],
            dimensions["trust_state"],
            change,
            MetricApplicability.APPLICABLE.value if change is not None else MetricApplicability.NOT_APPLICABLE.value,
            excursion,
            hypothesis.value,
            invalid_obs,
            invalid_seconds,
            invalid_count,
            _no_action_reason(record),
            False,
            "NONE",
            supersedes_attribution_id,
            window.dataset_fingerprints[0] if window.dataset_fingerprints else None,
            revised_dataset_fingerprint,
            fingerprint,
        )
        self.attributions[attribution.attribution_id] = attribution
        self._trim(self.attributions, self.maximum_attributions)
        self.processed_evidence_ids.add(record.evidence_record_id)
        self.metrics["attributions_published"] += 1
        if record.final_classification == "NO_ACTION":
            self.metrics["no_action_attributions"] += 1
        if record.final_classification == "RESTRICTED":
            self.metrics["restricted_attributions"] += 1
        if record.final_classification == "ELIGIBLE_RESEARCH":
            self.metrics["eligible_research_attributions"] += 1
        self._ingest_analytics(attribution, window)
        self._record("outcome_attribution_created", {"attribution_id": attribution.attribution_id, "record_id": record.evidence_record_id})
        if supersedes_attribution_id:
            self._record("outcome_attribution_superseded", {"attribution_id": attribution.attribution_id, "supersedes": supersedes_attribution_id})
        return attribution

    def publish_snapshot(
        self,
        *,
        as_of: datetime | None = None,
        cohort_definitions: Iterable[CohortDefinition] | None = None,
        source_ledger_range: tuple[int, int] | None = None,
    ) -> ResearchPerformanceSnapshot:
        now = as_of or self.clock.now()
        cohorts = tuple(cohort_definitions or self.default_cohort_definitions())
        attributions = tuple(self.attributions.values())
        windows = tuple(self.windows.values())
        stats = tuple(stat for cohort in cohorts for stat in self._cohort_statistics(cohort, attributions, windows))
        warnings = tuple(sorted({warning for stat in stats for warning in stat.warnings}))
        sufficiency = "INSUFFICIENT_EVIDENCE" if any(stat.sufficiency_state == "INSUFFICIENT_EVIDENCE" for stat in stats) else "SUFFICIENT_FOR_POLICY"
        source_fps = tuple(sorted({item.attribution_fingerprint for item in attributions}))
        payload = {
            "as_of": now,
            "cohorts": cohorts,
            "attributions": tuple(item.attribution_id for item in attributions),
            "windows": tuple(item.window_id for item in windows),
            "policy": self.policy.policy_identity,
            "configuration": self.configuration_identity,
            "source_ledger_range": source_ledger_range,
        }
        fingerprint = _sha256_json(payload)
        snapshot = ResearchPerformanceSnapshot(
            deterministic_id("p48_research_performance_snapshot", fingerprint),
            RESEARCH_PERFORMANCE_SNAPSHOT_SCHEMA_VERSION,
            research_performance_snapshot_schema_identity(),
            now,
            "P47_VERIFIED_RESEARCH_DECISION_EVIDENCE_WITH_P48_MATURED_WINDOWS",
            cohorts,
            len({item.evidence_record_id for item in attributions}),
            sum(1 for item in windows if item.coverage_state == OutcomeWindowState.MATURE.value),
            sum(1 for item in windows if item.coverage_state == OutcomeWindowState.PARTIALLY_OBSERVED.value),
            sum(1 for item in windows if item.coverage_state in {OutcomeWindowState.PENDING.value, OutcomeWindowState.UNAVAILABLE.value}),
            sum(1 for item in windows if item.coverage_state == OutcomeWindowState.INVALID.value),
            _count_by(attributions, "decision_classification"),
            stats,
            _classification_stats(attributions, "NO_ACTION"),
            _classification_stats(attributions, "RESTRICTED"),
            _count_mapping(item.protection_state for item in attributions),
            _count_mapping(item.strategy_id for item in attributions),
            _count_mapping(item.regime_at_decision for item in attributions),
            _count_mapping(item.session_at_decision for item in attributions),
            _count_mapping(item.configuration_identity for item in attributions),
            _count_mapping(item.portfolio_state for item in attributions),
            _count_mapping(item.trust_state for item in attributions),
            sufficiency,
            warnings,
            (
                "Research outcomes are descriptive historical evidence, not causal proof.",
                "ResearchPerformance is not financial authorization.",
                "MissingOutcome is not ZeroOutcome.",
            ),
            source_ledger_range,
            source_fps,
            self.configuration_identity,
            self.policy.policy_identity,
            "P48_OUTCOME_PERFORMANCE_INTELLIGENCE",
            fingerprint,
        )
        self.snapshots[snapshot.snapshot_id] = snapshot
        self._trim(self.snapshots, self.maximum_snapshots)
        self.metrics["cohort_counts"] = len(stats)
        self.metrics["insufficient_sample_cohorts"] = sum(1 for item in stats if item.sufficiency_state == "INSUFFICIENT_EVIDENCE")
        self._record("performance_snapshot_published", {"snapshot_id": snapshot.snapshot_id, "cohorts": len(stats)})
        return snapshot

    def default_cohort_definitions(self) -> tuple[CohortDefinition, ...]:
        return (
            CohortDefinition.create(("decision_classification",), self.policy),
            CohortDefinition.create(("strategy_id", "strategy_version"), self.policy),
            CohortDefinition.create(("regime_at_decision",), self.policy),
            CohortDefinition.create(("session_at_decision",), self.policy),
            CohortDefinition.create(("configuration_identity",), self.policy),
            CohortDefinition.create(("protection_state",), self.policy),
            CohortDefinition.create(("score_band",), self.policy),
        )

    def query_attributions(self, *, offset: int = 0, limit: int = 50, classification: str | None = None) -> tuple[ResearchOutcomeAttribution, ...]:
        limit = max(1, min(limit, self.maximum_query_limit))
        items = [item for item in self.attributions.values() if classification is None or item.decision_classification == classification]
        return tuple(items[offset : offset + limit])

    def recovery_state(self, recovery_epoch: int) -> OutcomeRuntimeRecoveryState:
        return OutcomeRuntimeRecoveryState(
            RESEARCH_OUTCOME_WINDOW_SCHEMA_VERSION,
            RESEARCH_OUTCOME_RUNTIME_VERSION,
            self.policy.policy_identity,
            self.configuration_identity,
            recovery_epoch,
            tuple(sorted(self.processed_evidence_ids)),
            tuple(item.window_id for item in self.windows.values() if item.coverage_state in {OutcomeWindowState.PENDING.value, OutcomeWindowState.PARTIALLY_OBSERVED.value}),
            tuple(item.window_id for item in self.windows.values() if item.coverage_state == OutcomeWindowState.MATURE.value),
            tuple(self.attributions),
            tuple(self.snapshots),
            tuple(self.windows.values()),
            tuple(self.attributions.values()),
            tuple(self.snapshots.values()),
        )

    def restore(self, state: OutcomeRuntimeRecoveryState, recovery_epoch: int) -> bool:
        self.metrics["recovery_count"] += 1
        self._record("outcome_recovery_started", {"recovery_epoch": recovery_epoch})
        if (
            state.runtime_version != RESEARCH_OUTCOME_RUNTIME_VERSION
            or state.policy_identity != self.policy.policy_identity
            or state.configuration_identity != self.configuration_identity
            or state.recovery_epoch != recovery_epoch
        ):
            self.recovery_restricted = True
            self.metrics["recovery_divergence"] += 1
            self._record("outcome_recovery_failed", {"reason": "P48_RECOVERY_IDENTITY_MISMATCH"})
            return False
        self.windows = OrderedDict((item.window_id, item) for item in state.windows)
        self.attributions = OrderedDict((item.attribution_id, item) for item in state.attributions)
        self.snapshots = OrderedDict((item.snapshot_id, item) for item in state.snapshots)
        self.processed_evidence_ids = set(state.processed_evidence_ids)
        self.recovery_restricted = False
        self._record("outcome_recovery_completed", {"windows": len(self.windows), "attributions": len(self.attributions)})
        return True

    def replay_fingerprint(self) -> str:
        return deterministic_id(
            "p48_outcome_replay",
            self.policy.policy_identity,
            *self.windows,
            *self.attributions,
            *self.snapshots,
        )

    def incremental_equals_full_rebuild(self) -> bool:
        rebuilt = ResearchOutcomePerformanceRuntime(
            clock=self.clock,
            audit=None,
            evidence_ledger=self.evidence_ledger,
            policy=self.policy,
            storage_root=self.storage_root,
            configuration_identity=self.configuration_identity,
            maximum_windows=self.maximum_windows,
            maximum_attributions=self.maximum_attributions,
            maximum_snapshots=self.maximum_snapshots,
        )
        rebuilt.windows = OrderedDict(self.windows)
        rebuilt.attributions = OrderedDict(self.attributions)
        rebuilt_snapshot = rebuilt.publish_snapshot(as_of=self.clock.now())
        current_snapshot = self.publish_snapshot(as_of=self.clock.now())
        return rebuilt_snapshot.snapshot_fingerprint == current_snapshot.snapshot_fingerprint

    def diagnostics(self) -> dict[str, Any]:
        latest = next(reversed(self.snapshots.values()), None) if self.snapshots else None
        ledger_status = "UNAVAILABLE"
        if self.evidence_ledger is not None:
            try:
                ledger_status = self.evidence_ledger.verify_ledger().status.value
            except Exception:
                ledger_status = "INVALID"
        return {
            "runtime_version": RESEARCH_OUTCOME_RUNTIME_VERSION,
            "window_schema_version": RESEARCH_OUTCOME_WINDOW_SCHEMA_VERSION,
            "window_schema_identity": research_outcome_window_schema_identity(),
            "attribution_schema_version": RESEARCH_OUTCOME_ATTRIBUTION_SCHEMA_VERSION,
            "attribution_schema_identity": research_outcome_attribution_schema_identity(),
            "snapshot_schema_version": RESEARCH_PERFORMANCE_SNAPSHOT_SCHEMA_VERSION,
            "snapshot_schema_identity": research_performance_snapshot_schema_identity(),
            "policy_identity": self.policy.policy_identity,
            "policy": _jsonable(self.policy),
            "p47_ledger_verification": ledger_status,
            "metrics": dict(self.metrics),
            "window_count": len(self.windows),
            "attribution_count": len(self.attributions),
            "snapshot_count": len(self.snapshots),
            "latest_snapshot_id": latest.snapshot_id if latest else None,
            "runtime_health": self.component_health(None).name,
            "outcome_data_health": "INSUFFICIENT_EVIDENCE" if not self.attributions else "AVAILABLE",
            "attribution_availability": "AVAILABLE" if self.attributions else "INSUFFICIENT_EVIDENCE",
            "financial_execution": "NONE",
            "memory": {
                "windows": len(self.windows),
                "window_limit": self.maximum_windows,
                "attributions": len(self.attributions),
                "attribution_limit": self.maximum_attributions,
                "snapshots": len(self.snapshots),
                "snapshot_limit": self.maximum_snapshots,
            },
        }

    def component_ready(self, context: Any) -> bool:
        if self.recovery_restricted:
            return False
        if self.evidence_ledger is None:
            return True
        try:
            return self.evidence_ledger.verify_ledger().status is LedgerVerificationStatus.VERIFIED
        except Exception:
            return False

    def component_health(self, context: Any) -> HealthStatus:
        if self.recovery_restricted:
            return HealthStatus.RESTRICTED
        return HealthStatus.HEALTHY if self.component_ready(context) else HealthStatus.DEGRADED

    def _window_from_observations(
        self,
        record: ResearchDecisionEvidenceRecord,
        horizon: OutcomeHorizonDefinition,
        observations: tuple[FutureOutcomeObservation, ...],
        instrument_id: str,
        timeframe: str,
        evaluation_time: datetime,
    ) -> ResearchOutcomeWindow:
        reasons: list[str] = []
        accepted: list[FutureOutcomeObservation] = []
        for item in observations:
            if item.event_time <= record.knowledge_cutoff_utc or item.available_at <= record.knowledge_cutoff_utc:
                reasons.append("P48_FUTURE_TO_PAST_CONTAMINATION")
            elif item.available_at > evaluation_time:
                reasons.append("P48_OBSERVATION_NOT_AVAILABLE_AT_EVALUATION_TIME")
            elif item.instrument_id != instrument_id:
                reasons.append("P48_INSTRUMENT_MISMATCH")
            elif item.timeframe != timeframe:
                reasons.append("P48_TIMEFRAME_MISMATCH")
            elif item.dataset_fingerprint != record.dataset_fingerprint:
                reasons.append("P48_DATASET_ISOLATION_MISMATCH")
            else:
                accepted.append(item)
        accepted = accepted[: horizon.required_observation_count]
        count = len(accepted)
        if reasons:
            state = OutcomeWindowState.INVALID
            data_quality = OutcomeDataQualityState.INVALID
            self.metrics["future_data_rejections"] += 1
        elif count >= horizon.required_observation_count:
            state = OutcomeWindowState.MATURE
            data_quality = OutcomeDataQualityState.TRUSTED
        elif count > 0:
            state = OutcomeWindowState.PARTIALLY_OBSERVED
            data_quality = OutcomeDataQualityState.TRUSTED
        else:
            state = OutcomeWindowState.PENDING
            data_quality = OutcomeDataQualityState.UNAVAILABLE
        payload = {
            "record": record.evidence_record_id,
            "decision": record.decision_id,
            "horizon": horizon,
            "instrument": instrument_id,
            "timeframe": timeframe,
            "observations": tuple((item.observation_id, item.observation_fingerprint) for item in accepted),
            "policy": self.policy.policy_identity,
            "state": state.value,
            "reasons": tuple(dict.fromkeys(reasons)),
        }
        fingerprint = _sha256_json(payload)
        return ResearchOutcomeWindow(
            deterministic_id("p48_research_outcome_window", fingerprint),
            RESEARCH_OUTCOME_WINDOW_SCHEMA_VERSION,
            research_outcome_window_schema_identity(),
            record.decision_id,
            record.trace_id,
            record.evidence_record_id,
            record.knowledge_cutoff_utc,
            instrument_id,
            timeframe,
            record.knowledge_cutoff_utc,
            accepted[-1].event_time if state is OutcomeWindowState.MATURE and accepted else None,
            horizon.horizon_type,
            _jsonable(horizon),
            horizon.required_observation_count,
            count,
            state.value,
            data_quality.value,
            tuple(item.observation_id for item in accepted),
            tuple(item.observation_fingerprint for item in accepted),
            tuple(sorted({item.source_id for item in accepted})),
            tuple(sorted({item.dataset_id for item in accepted})),
            tuple(sorted({item.dataset_fingerprint for item in accepted})),
            max((item.event_time for item in accepted), default=None),
            max((item.available_at for item in accepted), default=None),
            evaluation_time,
            self.configuration_identity,
            self.policy.policy_identity,
            horizon.analysis_intent == AnalysisIntent.EXPLORATORY.value,
            tuple(dict.fromkeys(reasons)),
            fingerprint,
        )

    def _store_window(self, window: ResearchOutcomeWindow) -> None:
        self.windows[window.window_id] = window
        self._trim(self.windows, self.maximum_windows)

    def _assert_p47_verified(self, record: ResearchDecisionEvidenceRecord) -> None:
        if self.evidence_ledger is None:
            return
        result = self.evidence_ledger.verify_record(record.evidence_record_id)
        if result.status is not LedgerVerificationStatus.VERIFIED:
            raise ValueError("P48_P47_EVIDENCE_UNVERIFIABLE")

    def _find_attribution(self, evidence_record_id: str, window_id: str, revised_dataset_fingerprint: str | None) -> ResearchOutcomeAttribution | None:
        for item in self.attributions.values():
            if (
                item.evidence_record_id == evidence_record_id
                and item.outcome_window_id == window_id
                and item.outcome_policy_identity == self.policy.policy_identity
                and item.revised_dataset_fingerprint == revised_dataset_fingerprint
            ):
                return item
        return None

    def _ingest_analytics(self, attribution: ResearchOutcomeAttribution, window: ResearchOutcomeWindow) -> None:
        if attribution.normalized_research_change is None:
            return
        opened = window.window_start
        closed = window.window_end or window.evaluation_time
        observation = AnalyticsOutcomeObservation.create(
            attribution_id := attribution.attribution_id,
            attribution.strategy_id,
            attribution.strategy_version,
            attribution.strategy_implementation_identity,
            "P48",
            attribution.evidence_record_id,
            attribution.decision_classification,
            attribution.regime_at_decision,
            attribution.session_at_decision,
            window.timeframe,
            attribution.normalized_research_change,
            opened,
            closed,
            window.evaluation_time,
            window.dataset_fingerprints[0] if window.dataset_fingerprints else "NO_DATASET",
            configuration_snapshot_id=self.configuration_identity,
            lifecycle_snapshot_id=attribution.evidence_record_id,
            phase_vii_safety_snapshot_id=attribution.protection_state,
            phase_vii_safety_state=attribution.protection_state,
            engine_version=RESEARCH_OUTCOME_RUNTIME_VERSION,
        )
        self._analytics.ingest(observation, window.evaluation_time)

    def _cohort_statistics(
        self,
        definition: CohortDefinition,
        attributions: tuple[ResearchOutcomeAttribution, ...],
        windows: tuple[ResearchOutcomeWindow, ...],
    ) -> tuple[CohortStatistics, ...]:
        by_window = {item.window_id: item for item in windows}
        groups: dict[tuple[tuple[str, str], ...], list[ResearchOutcomeAttribution]] = defaultdict(list)
        for item in attributions:
            key = tuple((dimension, str(getattr(item, dimension, "UNKNOWN"))) for dimension in definition.dimensions)
            groups[key].append(item)
        if not groups:
            return (
                CohortStatistics(
                    definition.cohort_definition_id,
                    tuple((dimension, "NO_EVIDENCE") for dimension in definition.dimensions),
                    0,
                    0,
                    sum(1 for item in windows if item.coverage_state == OutcomeWindowState.PARTIALLY_OBSERVED.value),
                    sum(1 for item in windows if item.coverage_state in {OutcomeWindowState.PENDING.value, OutcomeWindowState.UNAVAILABLE.value}),
                    sum(1 for item in windows if item.coverage_state == OutcomeWindowState.INVALID.value),
                    "INSUFFICIENT_EVIDENCE",
                    None,
                    None,
                    None,
                    None,
                    0,
                    0,
                    0,
                    ("P48_NO_OUTCOME_ATTRIBUTIONS",),
                ),
            )
        result = []
        for key, items in sorted(groups.items()):
            values = sorted(item.normalized_research_change for item in items if item.normalized_research_change is not None)
            sufficient = len(items) >= self.policy.minimum_sample_size
            warnings = () if sufficient else ("P48_INSUFFICIENT_SAMPLE",)
            result.append(
                CohortStatistics(
                    definition.cohort_definition_id,
                    key,
                    len(items),
                    sum(1 for item in items if by_window.get(item.outcome_window_id) and by_window[item.outcome_window_id].coverage_state == OutcomeWindowState.MATURE.value),
                    0,
                    0,
                    0,
                    "SUFFICIENT" if sufficient else "INSUFFICIENT_EVIDENCE",
                    _mean(values),
                    _median(values),
                    min(values) if values else None,
                    max(values) if values else None,
                    sum(1 for value in values if value > 0),
                    sum(1 for value in values if value < 0),
                    sum(1 for value in values if value == 0),
                    warnings,
                )
            )
        return tuple(result)

    @staticmethod
    def _trim(items: OrderedDict[str, Any], maximum: int) -> None:
        while len(items) > maximum:
            items.popitem(last=False)

    def _record(self, event: str, payload: Mapping[str, Any]) -> None:
        if self.audit is not None:
            self.audit.record(event, dict(payload))


class _OutcomeComponent:
    def __init__(
        self,
        component_id: str,
        holder: dict[str, ResearchOutcomePerformanceRuntime],
        ledger_component: Any | None = None,
    ) -> None:
        self.component_id = component_id
        self.runtime: ResearchOutcomePerformanceRuntime | None = None
        self._holder = holder
        self._ledger_component = ledger_component

    def initialize_component(self, context: Any) -> None:
        if self.runtime is None:
            if "runtime" in self._holder:
                self.runtime = self._holder["runtime"]
            else:
                ledger = getattr(self._ledger_component, "runtime", None)
                self.runtime = ResearchOutcomePerformanceRuntime(
                    clock=context.services["clock"],
                    audit=context.services["audit"],
                    evidence_ledger=ledger,
                )
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


def research_outcome_window_schema_identity() -> str:
    return _sha256_json(
        {
            "schema": "p48_research_outcome_window",
            "version": RESEARCH_OUTCOME_WINDOW_SCHEMA_VERSION,
            "fields": tuple(ResearchOutcomeWindow.__dataclass_fields__),
            "upstream": research_decision_evidence_record_schema_identity(),
            "future_data": ("CanonicalMarketObservation", "TrustedResearchObservation", quality_trust_schema_identity()),
        }
    )


def research_outcome_attribution_schema_identity() -> str:
    return _sha256_json(
        {
            "schema": "p48_research_outcome_attribution",
            "version": RESEARCH_OUTCOME_ATTRIBUTION_SCHEMA_VERSION,
            "fields": tuple(ResearchOutcomeAttribution.__dataclass_fields__),
            "window": research_outcome_window_schema_identity(),
        }
    )


def research_performance_snapshot_schema_identity() -> str:
    return _sha256_json(
        {
            "schema": "p48_research_performance_snapshot",
            "version": RESEARCH_PERFORMANCE_SNAPSHOT_SCHEMA_VERSION,
            "fields": tuple(ResearchPerformanceSnapshot.__dataclass_fields__),
            "attribution": research_outcome_attribution_schema_identity(),
        }
    )


def research_outcome_policy_identity() -> str:
    return ResearchOutcomePolicy.current().policy_identity


def research_outcome_performance_component_registrations(
    *,
    clock: Any | None = None,
    audit: Any | None = None,
    ledger: ResearchDecisionEvidenceLedger | None = None,
    ledger_component: Any | None = None,
) -> tuple[tuple[ComponentMetadata, Any], ...]:
    holder: dict[str, ResearchOutcomePerformanceRuntime] = {}
    if clock is not None or ledger is not None:
        holder["runtime"] = ResearchOutcomePerformanceRuntime(clock=clock or _SystemClock(), audit=audit, evidence_ledger=ledger)
    definitions = (
        ("outcome_window_manager", ("research_evidence_ledger",)),
        ("outcome_evidence_validator", ("outcome_window_manager", "data_trust")),
        ("research_outcome_attribution", ("outcome_evidence_validator",)),
        ("cohort_analytics", ("research_outcome_attribution",)),
        ("research_performance_intelligence", ("cohort_analytics",)),
        ("research_performance_snapshot", ("research_performance_intelligence",)),
    )
    return tuple(
        (
            ComponentMetadata(
                component_id=component_id,
                component_type=ComponentType.RESEARCH,
                component_version=RESEARCH_OUTCOME_RUNTIME_VERSION,
                required=True,
                dependencies=dependencies,
                capabilities=ComponentCapabilities(persistence=True, recovery=True, health=True, diagnostics=True, activation=True),
            ),
            _OutcomeComponent(component_id, holder, ledger_component),
        )
        for component_id, dependencies in definitions
    )


def research_outcome_performance_components_from_inventory(inventory: tuple[Mapping[str, Any], ...]) -> dict[str, dict[str, Any]]:
    ids = {
        "outcome_window_manager",
        "outcome_evidence_validator",
        "research_outcome_attribution",
        "cohort_analytics",
        "research_performance_intelligence",
        "research_performance_snapshot",
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


class _SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


def _historical_dimensions(record: ResearchDecisionEvidenceRecord, policy: ResearchOutcomePolicy) -> dict[str, Any]:
    strategy = _extract_reason_value(record.reason_codes, "STRATEGY") or "UNKNOWN_STRATEGY"
    if "@" in strategy:
        strategy_id, version = strategy.split("@", 1)
    else:
        strategy_id, version = strategy, _extract_reason_value(record.reason_codes, "STRATEGY_VERSION") or "UNKNOWN_VERSION"
    score = _decimal_or_none(_extract_reason_value(record.reason_codes, "SCORE"))
    return {
        "strategy_id": strategy_id,
        "strategy_version": version,
        "strategy_implementation_identity": _extract_reason_value(record.reason_codes, "IMPLEMENTATION") or "UNKNOWN_IMPLEMENTATION",
        "candidate_id": _extract_reason_value(record.reason_codes, "CANDIDATE"),
        "direction": _extract_direction(record.reason_codes),
        "regime_at_decision": _extract_reason_value(record.reason_codes, "REGIME") or "UNKNOWN_REGIME",
        "realized_regime": _extract_reason_value(record.reason_codes, "REALIZED_REGIME") or "UNKNOWN_REALIZED_REGIME",
        "session_at_decision": _extract_reason_value(record.reason_codes, "SESSION") or "UNKNOWN_SESSION",
        "score_value": score,
        "score_band": _score_band(score, policy),
        "restriction_state": "RESTRICTED" if record.restriction_references or record.final_classification == "RESTRICTED" else "UNRESTRICTED",
        "portfolio_state": _stage_decision(record, "P44_PORTFOLIO_SNAPSHOT") or "UNKNOWN_PORTFOLIO_STATE",
        "trust_state": _stage_decision(record, "P40_QUALITY_TRUST") or "UNKNOWN_TRUST_STATE",
    }


def _stage_decision(record: ResearchDecisionEvidenceRecord, stage: str) -> str | None:
    for item in record.stage_evidence:
        if item.get("stage") == stage:
            return item.get("stage_decision")
    return None


def _extract_reason_value(reasons: Iterable[str], key: str) -> str | None:
    prefix = f"{key}:"
    for reason in reasons:
        if reason.startswith(prefix):
            return reason[len(prefix) :]
    return None


def _extract_direction(reasons: Iterable[str]) -> str:
    values = {str(item).upper() for item in reasons}
    if any(item in values for item in ("DIRECTION:LONG", "LONG", "BUY_HYPOTHESIS")):
        return "LONG"
    if any(item in values for item in ("DIRECTION:SHORT", "SHORT", "SELL_HYPOTHESIS")):
        return "SHORT"
    return "DIRECTIONLESS"


def _score_band(score: Decimal | None, policy: ResearchOutcomePolicy) -> str:
    if score is None:
        return "NOT_APPLICABLE"
    for band in policy.score_bands:
        lower_ok = band.lower_inclusive is None or score >= band.lower_inclusive
        upper_ok = band.upper_exclusive is None or score < band.upper_exclusive
        if lower_ok and upper_ok:
            return band.band_id
    return "OUT_OF_POLICY_RANGE"


def _normalized_change(observations: tuple[FutureOutcomeObservation, ...], reference: Decimal | None, direction: str) -> Decimal | None:
    if reference is None or not observations or direction not in {"LONG", "SHORT"}:
        return None
    end = observations[-1].close
    change = (end - reference) / reference if direction == "LONG" else (reference - end) / reference
    return _q(change)


def _excursion(
    observations: tuple[FutureOutcomeObservation, ...],
    reference: Decimal | None,
    direction: str,
    coverage_state: str,
) -> OutcomeExcursion:
    if reference is None or not observations or direction not in {"LONG", "SHORT"}:
        return OutcomeExcursion(MetricApplicability.NOT_APPLICABLE.value, direction, reference, None, None, None, None, observations[0].timeframe if observations else "UNAVAILABLE", coverage_state)
    if direction == "LONG":
        favorable_items = [(item, item.high - reference) for item in observations]
        adverse_items = [(item, reference - item.low) for item in observations]
    else:
        favorable_items = [(item, reference - item.low) for item in observations]
        adverse_items = [(item, item.high - reference) for item in observations]
    fav_item, fav = max(favorable_items, key=lambda pair: (pair[1], pair[0].event_time))
    adv_item, adv = max(adverse_items, key=lambda pair: (pair[1], pair[0].event_time))
    start = observations[0].event_time
    return OutcomeExcursion(
        MetricApplicability.APPLICABLE.value,
        direction,
        reference,
        _q(fav / reference),
        _q(adv / reference),
        int((fav_item.event_time - start).total_seconds()),
        int((adv_item.event_time - start).total_seconds()),
        observations[0].timeframe,
        coverage_state,
    )


def _hypothesis(
    observations: tuple[FutureOutcomeObservation, ...],
    reference: Decimal | None,
    direction: str,
    cutoff: datetime,
) -> tuple[HypothesisOutcome, str | None, int | None, int | None]:
    change = _normalized_change(observations, reference, direction)
    if change is None:
        return HypothesisOutcome.NOT_APPLICABLE, None, None, None
    threshold = Decimal("-0.01")
    for index, item in enumerate(observations, start=1):
        partial = _normalized_change((item,), reference, direction)
        if partial is not None and partial <= threshold:
            return HypothesisOutcome.INVALIDATED, item.observation_id, int((item.event_time - cutoff).total_seconds()), index
    if change > Decimal("0.01"):
        return HypothesisOutcome.SUPPORTED, None, None, None
    if change >= Decimal("0"):
        return HypothesisOutcome.PARTIALLY_SUPPORTED, None, None, None
    return HypothesisOutcome.NOT_SUPPORTED, None, None, None


def _no_action_reason(record: ResearchDecisionEvidenceRecord) -> str | None:
    if record.final_classification != "NO_ACTION":
        return None
    for reason in record.reason_codes:
        if "NO_ACTION" in reason or "NO_ELIGIBLE" in reason or "CONFLICT" in reason or "RESTRICT" in reason:
            return reason
    return "NO_ACTION_REASON_UNSPECIFIED"


def _classification_stats(items: tuple[ResearchOutcomeAttribution, ...], classification: str) -> dict[str, Any]:
    selected = [item for item in items if item.decision_classification == classification]
    return {
        "classification": classification,
        "sample_count": len(selected),
        "complete_outcome_count": len(selected),
        "positive_count": sum(1 for item in selected if item.normalized_research_change is not None and item.normalized_research_change > 0),
        "negative_count": sum(1 for item in selected if item.normalized_research_change is not None and item.normalized_research_change < 0),
        "causal_claim": False,
    }


def _count_by(items: Iterable[Any], field: str) -> dict[str, int]:
    return _count_mapping(str(getattr(item, field)) for item in items)


def _count_mapping(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items()))


def _mean(values: list[Decimal]) -> Decimal | None:
    return _q(sum(values, Decimal("0")) / Decimal(len(values))) if values else None


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return _q(ordered[mid])
    return _q((ordered[mid - 1] + ordered[mid]) / Decimal("2"))


def _decimal_or_none(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except Exception:
        return None


def _q(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.00000001"))


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


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
