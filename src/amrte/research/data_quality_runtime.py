from __future__ import annotations

import hashlib
import json
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from amrte.core.composition import ComponentCapabilities, ComponentMetadata, ComponentType
from amrte.core.identity import deterministic_id
from amrte.core.types import HealthStatus
from amrte.market.observation import (
    CanonicalMarketDataset,
    CanonicalMarketObservation,
    ValidationReason,
    ValidationStatus,
    validate_canonical_observation,
)
from amrte.market.service import TIMEFRAME_SECONDS
from amrte.research.observation_quality import (
    ObservationHealth,
    ObservationQualityEngine,
    QualityConfiguration,
    ResearchQualityState,
    ScalarObservation,
)
from amrte.research.reliability import (
    QualityOutcomeDelta,
    ReliabilityConfiguration,
    ReliabilityDecision,
    ResearchReliabilityEngine,
)
from amrte.research.system_safety import (
    SafetyDecision,
    SafetyDomain,
    SignalSeverity,
    SystemSafetyConfiguration,
    SystemSafetyEngine,
    SystemSafetySignal,
)
from amrte.research.temporal_quality import (
    OutcomeClass,
    TemporalDecision,
    TemporalQualityConfiguration,
    TemporalQualityOutcome,
    TemporalQualityProtectionEngine,
)


QUALITY_TRUST_SCHEMA_VERSION = "1.0"
DATA_QUALITY_RUNTIME_VERSION = "1.0"


class TrustStatus(Enum):
    TRUSTED = "TRUSTED"
    TRUSTED_WITH_WARNINGS = "TRUSTED_WITH_WARNINGS"
    RESTRICTED = "RESTRICTED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"
    UNAVAILABLE = "UNAVAILABLE"


class FreshnessState(Enum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ContinuityState(Enum):
    INITIALIZING = "INITIALIZING"
    HEALTHY = "HEALTHY"
    INTERRUPTED = "INTERRUPTED"
    STALE = "STALE"
    RECOVERING = "RECOVERING"
    RECOVERED = "RECOVERED"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"


class ProcessingMode(Enum):
    STRICT = "STRICT"
    DIAGNOSTIC = "DIAGNOSTIC"
    REPLAY = "REPLAY"


@dataclass(frozen=True)
class DataQualityRuntimeConfiguration:
    staleness_multiplier: Decimal = Decimal("2")
    trusted_quality_states: tuple[str, ...] = ("HEALTHY",)
    warning_quality_states: tuple[str, ...] = ("DEGRADED",)
    maximum_snapshots: int = 2048
    maximum_history_per_scope: int = 512
    maximum_diagnostics: int = 256
    configuration_snapshot_id: str = "P40_DATA_QUALITY_TRUST_DEFAULT"

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.staleness_multiplier < Decimal("1"):
            errors.append("P40_STALENESS_MULTIPLIER_INVALID")
        if min(self.maximum_snapshots, self.maximum_history_per_scope, self.maximum_diagnostics) < 1:
            errors.append("P40_BOUNDS_INVALID")
        if not self.trusted_quality_states:
            errors.append("P40_TRUSTED_QUALITY_STATES_EMPTY")
        return tuple(errors)


@dataclass(frozen=True)
class IngestionEnvelope:
    ingestion_id: str
    observation_id: str
    observation_fingerprint: str
    dataset_id: str
    dataset_fingerprint: str
    source_id: str
    schema_version: str
    configuration_identity: str
    recovery_epoch: int
    logical_time: datetime
    processing_mode: str


@dataclass(frozen=True)
class QualityTrustSnapshot:
    snapshot_id: str
    schema_version: str
    as_of: datetime
    observation_id: str
    observation_fingerprint: str
    dataset_id: str
    dataset_fingerprint: str
    source_id: str
    scope_id: str
    structural_status: str
    provenance_status: str
    duplicate_status: str
    sequence_status: str
    temporal_status: str
    freshness: FreshnessState
    quality_status: str
    reliability_status: str
    source_health_status: str
    trust_status: TrustStatus
    blocking_reasons: tuple[str, ...]
    warning_reasons: tuple[str, ...]
    configuration_identity: str
    recovery_epoch: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SourceHealthSnapshot:
    snapshot_id: str
    source_id: str
    dataset_id: str
    scope_id: str
    status: ContinuityState
    as_of: datetime
    last_received: datetime | None
    last_trusted: datetime | None
    freshness: FreshnessState
    received_count: int
    trusted_count: int
    restricted_count: int
    quarantined_count: int
    rejected_count: int
    duplicate_count: int
    collision_count: int
    gap_count: int
    out_of_order_count: int
    blocking_reasons: tuple[str, ...]
    warning_reasons: tuple[str, ...]


@dataclass(frozen=True)
class TrustedResearchObservation:
    trusted_observation_id: str
    envelope: IngestionEnvelope
    quality_snapshot_id: str
    reliability_snapshot_id: str | None
    temporal_snapshot_id: str | None
    source_health_snapshot_id: str
    trust_status: TrustStatus
    as_of: datetime
    blocking_reasons: tuple[str, ...]
    warning_reasons: tuple[str, ...]
    authoritative_effect_applied: bool


@dataclass(frozen=True)
class DataQualityRecoveryState:
    schema_version: str
    runtime_version: str
    configuration_identity: str
    recovery_epoch: int
    processed_keys: tuple[tuple[str, str], ...]
    fingerprints_by_identity: tuple[tuple[str, str], ...]
    last_sequence_by_scope: tuple[tuple[str, int], ...]
    last_event_time_by_scope: tuple[tuple[str, datetime], ...]
    last_trusted_by_scope: tuple[tuple[str, str], ...]
    counters_by_scope: tuple[tuple[str, Mapping[str, int]], ...]
    snapshots: tuple[QualityTrustSnapshot, ...]
    trusted: tuple[TrustedResearchObservation, ...]
    source_health: tuple[SourceHealthSnapshot, ...]
    quality_state: Any
    reliability_state: Any
    temporal_state: Any
    safety_state: Any


@dataclass(frozen=True)
class BatchIngestionReport:
    report_id: str
    dataset_id: str
    received: int
    schema_valid: int
    provenance_valid: int
    duplicates: int
    conflicts: int
    out_of_order: int
    temporally_eligible: int
    stale: int
    trusted: int
    restricted: int
    quarantined: int
    rejected: int
    final_cursor: str | None


@dataclass
class _ScopeState:
    counters: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    last_received: datetime | None = None
    last_trusted: datetime | None = None
    latest_health: SourceHealthSnapshot | None = None


def quality_trust_schema_identity() -> str:
    payload = {
        "schema": "p40_quality_trust",
        "version": QUALITY_TRUST_SCHEMA_VERSION,
        "trust_states": tuple(item.value for item in TrustStatus),
        "snapshot_fields": tuple(QualityTrustSnapshot.__dataclass_fields__),
        "trusted_observation_fields": tuple(TrustedResearchObservation.__dataclass_fields__),
    }
    return _sha256_json(payload)


class DataQualityTrustRuntime:
    """Single governed ingestion authority for P39 canonical observations."""

    def __init__(
        self,
        configuration: DataQualityRuntimeConfiguration = DataQualityRuntimeConfiguration(),
        *,
        audit: Any = None,
        quality_engine: ObservationQualityEngine | None = None,
        reliability_engine: ResearchReliabilityEngine | None = None,
        temporal_engine: TemporalQualityProtectionEngine | None = None,
        safety_engine: SystemSafetyEngine | None = None,
    ) -> None:
        errors = configuration.validate()
        if errors:
            raise ValueError(";".join(errors))
        self.configuration = configuration
        self.audit = audit
        self.quality = quality_engine or ObservationQualityEngine(
            QualityConfiguration(
                configuration_snapshot_id=configuration.configuration_snapshot_id,
                recovery_confirmations=1,
                repeated_failure_limit=1_000_000,
            ),
            audit,
        )
        self.reliability = reliability_engine or ResearchReliabilityEngine(
            ReliabilityConfiguration(configuration_snapshot_id=configuration.configuration_snapshot_id),
            audit,
        )
        self.temporal = temporal_engine or TemporalQualityProtectionEngine(
            TemporalQualityConfiguration(configuration_snapshot_id=configuration.configuration_snapshot_id),
            audit,
        )
        self.safety = safety_engine or SystemSafetyEngine(
            SystemSafetyConfiguration(configuration_snapshot_id=configuration.configuration_snapshot_id),
            audit,
        )
        self._processed: OrderedDict[str, TrustedResearchObservation] = OrderedDict()
        self._fingerprints_by_identity: dict[str, str] = {}
        self._last_sequence_by_scope: dict[str, int] = {}
        self._last_event_time_by_scope: dict[str, datetime] = {}
        self._history_by_scope: dict[str, tuple[ScalarObservation, ...]] = defaultdict(tuple)
        self._last_trusted_by_scope: dict[str, str] = {}
        self._states: dict[str, _ScopeState] = defaultdict(_ScopeState)
        self.snapshots: OrderedDict[str, QualityTrustSnapshot] = OrderedDict()
        self.trusted_observations: OrderedDict[str, TrustedResearchObservation] = OrderedDict()
        self.source_health: OrderedDict[str, SourceHealthSnapshot] = OrderedDict()
        self.recovery_restricted = False

    @property
    def configuration_identity(self) -> str:
        return self.configuration.configuration_snapshot_id

    def ingest_dataset(
        self,
        dataset: CanonicalMarketDataset,
        *,
        logical_time: datetime,
        recovery_epoch: int = 0,
        processing_mode: ProcessingMode = ProcessingMode.STRICT,
    ) -> BatchIngestionReport:
        results = tuple(
            self.ingest_observation(
                observation,
                dataset=dataset,
                logical_time=logical_time,
                recovery_epoch=recovery_epoch,
                processing_mode=processing_mode,
            )
            for observation in dataset.observations
        )
        snapshots = tuple(self.snapshots[item.quality_snapshot_id] for item in results)
        final_cursor = results[-1].trusted_observation_id if results else None
        report_id = deterministic_id(
            "p40_batch_ingestion_report",
            dataset.manifest.dataset_id,
            dataset.manifest.dataset_fingerprint,
            logical_time.isoformat(),
            final_cursor or "NONE",
        )
        return BatchIngestionReport(
            report_id,
            dataset.manifest.dataset_id,
            len(results),
            sum(item.structural_status == "VALID" for item in snapshots),
            sum(item.provenance_status == "VALID" for item in snapshots),
            sum("EXACT_DUPLICATE" in item.warning_reasons for item in snapshots),
            sum("IDENTITY_COLLISION" in item.blocking_reasons for item in snapshots),
            sum("OUT_OF_ORDER" in item.blocking_reasons for item in snapshots),
            sum("FUTURE_TIMESTAMP" not in item.blocking_reasons for item in snapshots),
            sum(item.freshness is FreshnessState.STALE for item in snapshots),
            sum(item.trust_status in (TrustStatus.TRUSTED, TrustStatus.TRUSTED_WITH_WARNINGS) for item in snapshots),
            sum(item.trust_status is TrustStatus.RESTRICTED for item in snapshots),
            sum(item.trust_status is TrustStatus.QUARANTINED for item in snapshots),
            sum(item.trust_status is TrustStatus.REJECTED for item in snapshots),
            final_cursor,
        )

    def ingest_observation(
        self,
        observation: CanonicalMarketObservation,
        *,
        dataset: CanonicalMarketDataset | None = None,
        logical_time: datetime,
        recovery_epoch: int = 0,
        processing_mode: ProcessingMode = ProcessingMode.STRICT,
    ) -> TrustedResearchObservation:
        as_of = _aware_utc(logical_time)
        dataset_id = dataset.manifest.dataset_id if dataset else observation.source.source_dataset
        dataset_fingerprint = dataset.manifest.dataset_fingerprint if dataset else observation.source.source_version
        envelope = self._envelope(observation, dataset_id, dataset_fingerprint, as_of, recovery_epoch, processing_mode)
        if envelope.ingestion_id in self._processed:
            original = self._processed[envelope.ingestion_id]
            return replace(original, authoritative_effect_applied=False)

        scope_id = self._scope(observation, dataset_id)
        state = self._states[scope_id]
        state.counters["received"] += 1
        state.last_received = observation.received_at
        blockers: list[str] = []
        warnings: list[str] = []
        structural_status = "VALID"
        provenance_status = "VALID"
        duplicate_status = "UNIQUE"
        sequence_status = "NOT_APPLICABLE"
        temporal_status = "ELIGIBLE"

        validation = validate_canonical_observation(observation, logical_time=as_of)
        if not validation.valid:
            structural_status = "INVALID"
            blockers.extend(issue.reason.value for issue in validation.issues)
        if observation.source.source_id and observation.source.adapter_type and observation.source.adapter_version and observation.source.source_dataset and observation.provenance.source_record_locator and observation.provenance.transformations:
            state.counters["provenance_valid"] += 1
        else:
            provenance_status = "MISSING"
            blockers.append("PROVENANCE_MISSING")

        existing = self._fingerprints_by_identity.get(observation.observation_id)
        if existing == observation.observation_fingerprint:
            duplicate_status = "EXACT_DUPLICATE"
            warnings.append("EXACT_DUPLICATE")
            state.counters["duplicates"] += 1
        elif existing is not None:
            duplicate_status = "IDENTITY_COLLISION"
            blockers.append("IDENTITY_COLLISION")
            state.counters["collisions"] += 1

        previous_sequence = self._last_sequence_by_scope.get(scope_id)
        if observation.sequence is not None:
            if previous_sequence is None:
                sequence_status = "INITIAL"
            elif observation.sequence == previous_sequence:
                sequence_status = "DUPLICATE_SEQUENCE"
                warnings.append("DUPLICATE_SEQUENCE")
            elif observation.sequence < previous_sequence:
                sequence_status = "SEQUENCE_REGRESSION"
                blockers.append("SEQUENCE_REGRESSION")
            elif observation.sequence > previous_sequence + 1:
                sequence_status = "GAP_DETECTED"
                warnings.append("SEQUENCE_GAP")
                state.counters["gaps"] += 1
            else:
                sequence_status = "MONOTONIC"

        previous_time = self._last_event_time_by_scope.get(scope_id)
        if previous_time is not None and observation.event_time < previous_time:
            temporal_status = "OUT_OF_ORDER"
            blockers.append("OUT_OF_ORDER")
            state.counters["out_of_order"] += 1
        if observation.available_at > as_of:
            temporal_status = "FUTURE_UNAVAILABLE"
            blockers.append("FUTURE_TIMESTAMP")
        freshness = self._freshness(observation, as_of)
        if freshness is FreshnessState.STALE:
            warnings.append("STALE")
            state.counters["stale"] += 1

        scalar = self._scalar(observation, dataset_id, dataset_fingerprint)
        history = self._history_by_scope[scope_id]
        quality_snapshot = self.quality.evaluate(scalar if structural_status == "VALID" else None, history, as_of, recovery_epoch)
        quality_status = quality_snapshot.published_state.name
        if quality_snapshot.published_state.name not in self.configuration.trusted_quality_states:
            if quality_snapshot.published_state.name in self.configuration.warning_quality_states:
                warnings.append(f"QUALITY_{quality_snapshot.published_state.name}")
            else:
                blockers.append(f"QUALITY_{quality_snapshot.published_state.name}")

        self._ensure_scope_engines(scope_id, dataset_fingerprint, as_of, recovery_epoch)
        temporal_result = self._process_temporal(scope_id, observation, dataset_fingerprint, as_of, recovery_epoch, quality_snapshot.restriction_multiplier)
        reliability_result = self._process_reliability(scope_id, observation, dataset_fingerprint, as_of, recovery_epoch, blockers, warnings)
        safety_result = self._process_safety(scope_id, observation, dataset_fingerprint, as_of, recovery_epoch, blockers)
        if temporal_result.decision is TemporalDecision.BLOCKED:
            blockers.extend(temporal_result.reason_codes)
        if reliability_result.decision is ReliabilityDecision.BLOCKED:
            blockers.extend(reliability_result.reason_codes)
        elif reliability_result.index is not None and reliability_result.index.published_stage.name in {"PROTECTED", "SUSPENDED", "UNKNOWN"}:
            blockers.append(f"RELIABILITY_{reliability_result.index.published_stage.name}")
        elif reliability_result.index is not None and reliability_result.index.published_stage.name in {"WATCH", "RESTRICTED"}:
            warnings.append(f"RELIABILITY_{reliability_result.index.published_stage.name}")
        if safety_result.decision is SafetyDecision.BLOCKED:
            blockers.extend(safety_result.reason_codes)

        trust = self._trust(blockers, warnings, duplicate_status, structural_status, provenance_status)
        unique_blockers = tuple(dict.fromkeys(blockers))
        unique_warnings = tuple(dict.fromkeys(warnings))
        health = self._source_health(scope_id, observation, dataset_id, trust, freshness, as_of, state, unique_blockers, unique_warnings)
        snapshot_id = deterministic_id(
            "p40_quality_trust_snapshot",
            envelope.ingestion_id,
            structural_status,
            provenance_status,
            duplicate_status,
            sequence_status,
            temporal_status,
            freshness.value,
            quality_status,
            trust.value,
            *unique_blockers,
            *unique_warnings,
        )
        snapshot = QualityTrustSnapshot(
            snapshot_id,
            QUALITY_TRUST_SCHEMA_VERSION,
            as_of,
            observation.observation_id,
            observation.observation_fingerprint,
            dataset_id,
            dataset_fingerprint,
            observation.source.source_id,
            scope_id,
            structural_status,
            provenance_status,
            duplicate_status,
            sequence_status,
            temporal_status,
            freshness,
            quality_status,
            getattr(reliability_result.index, "published_stage", None).name if reliability_result.index else "UNAVAILABLE",
            health.status.value,
            trust,
            unique_blockers,
            unique_warnings,
            self.configuration_identity,
            recovery_epoch,
            tuple(item for item in (
                quality_snapshot.snapshot_id,
                getattr(reliability_result.event, "event_id", None),
                getattr(temporal_result.event, "event_id", None),
                getattr(safety_result.event, "event_id", None),
            ) if item),
        )
        trusted_id = deterministic_id("trusted_research_observation", envelope.ingestion_id, snapshot_id, trust.value)
        applied = trust in (TrustStatus.TRUSTED, TrustStatus.TRUSTED_WITH_WARNINGS, TrustStatus.RESTRICTED) and duplicate_status != "EXACT_DUPLICATE"
        result = TrustedResearchObservation(
            trusted_id,
            envelope,
            snapshot.snapshot_id,
            getattr(reliability_result.index, "index_id", None),
            getattr(temporal_result.state, "state_id", None),
            health.snapshot_id,
            trust,
            as_of,
            unique_blockers,
            unique_warnings,
            applied,
        )
        self.snapshots[snapshot.snapshot_id] = snapshot
        self.source_health[health.snapshot_id] = health
        self._processed[envelope.ingestion_id] = result
        self.trusted_observations[trusted_id] = result
        if existing is None:
            self._fingerprints_by_identity[observation.observation_id] = observation.observation_fingerprint
        if applied:
            if observation.sequence is not None:
                self._last_sequence_by_scope[scope_id] = observation.sequence
            self._last_event_time_by_scope[scope_id] = observation.event_time
            self._history_by_scope[scope_id] = (history + (scalar,))[-self.configuration.maximum_history_per_scope:]
        if trust in (TrustStatus.TRUSTED, TrustStatus.TRUSTED_WITH_WARNINGS):
            self._last_trusted_by_scope[scope_id] = observation.observation_id
            state.last_trusted = observation.event_time
        self._bound()
        self._record("observation_trust_classified", {"observation_id": observation.observation_id, "trust_status": trust.value, "snapshot_id": snapshot.snapshot_id})
        return result

    def recovery_state(self, recovery_epoch: int) -> DataQualityRecoveryState:
        return DataQualityRecoveryState(
            QUALITY_TRUST_SCHEMA_VERSION,
            DATA_QUALITY_RUNTIME_VERSION,
            self.configuration_identity,
            recovery_epoch,
            tuple(sorted((key, value.trusted_observation_id) for key, value in self._processed.items())),
            tuple(sorted(self._fingerprints_by_identity.items())),
            tuple(sorted(self._last_sequence_by_scope.items())),
            tuple(sorted(self._last_event_time_by_scope.items())),
            tuple(sorted(self._last_trusted_by_scope.items())),
            tuple(sorted((scope, MappingProxyType(dict(state.counters))) for scope, state in self._states.items())),
            tuple(self.snapshots.values()),
            tuple(self.trusted_observations.values()),
            tuple(self.source_health.values()),
            self.quality.recovery_state(recovery_epoch),
            self.reliability.recovery_state(recovery_epoch),
            self.temporal.recovery_state(recovery_epoch),
            self.safety.recovery_state(recovery_epoch),
        )

    def restore(self, state: DataQualityRecoveryState, expected_recovery_epoch: int) -> bool:
        if state.schema_version != QUALITY_TRUST_SCHEMA_VERSION or state.runtime_version != DATA_QUALITY_RUNTIME_VERSION or state.configuration_identity != self.configuration_identity or state.recovery_epoch != expected_recovery_epoch:
            self.recovery_restricted = True
            return False
        try:
            if not self.quality.restore(state.quality_state, expected_recovery_epoch):
                raise ValueError("quality restore failed")
            if not self.reliability.restore(state.reliability_state, expected_recovery_epoch):
                raise ValueError("reliability restore failed")
            if not self.temporal.restore(state.temporal_state, expected_recovery_epoch):
                raise ValueError("temporal restore failed")
            if not self.safety.restore(state.safety_state, expected_recovery_epoch):
                raise ValueError("safety restore failed")
            trusted = OrderedDict((item.trusted_observation_id, item) for item in state.trusted)
            snapshots = OrderedDict((item.snapshot_id, item) for item in state.snapshots)
            source_health = OrderedDict((item.snapshot_id, item) for item in state.source_health)
            if len(trusted) != len(state.trusted) or len(snapshots) != len(state.snapshots):
                raise ValueError("duplicate recovery evidence")
            if any(item.quality_snapshot_id not in snapshots for item in trusted.values()):
                raise ValueError("trusted observation without quality snapshot")
            self.trusted_observations = trusted
            self.snapshots = snapshots
            self.source_health = source_health
            self._fingerprints_by_identity = dict(state.fingerprints_by_identity)
            self._last_sequence_by_scope = dict(state.last_sequence_by_scope)
            self._last_event_time_by_scope = dict(state.last_event_time_by_scope)
            self._last_trusted_by_scope = dict(state.last_trusted_by_scope)
            self._processed = OrderedDict()
            by_id = {item.trusted_observation_id: item for item in state.trusted}
            for ingestion_id, trusted_id in state.processed_keys:
                if trusted_id not in by_id:
                    raise ValueError("processed key target missing")
                self._processed[ingestion_id] = by_id[trusted_id]
            self._states = defaultdict(_ScopeState)
            for scope, counters in state.counters_by_scope:
                self._states[scope].counters.update(dict(counters))
            self.recovery_restricted = False
            return True
        except Exception:
            self.recovery_restricted = True
            return False

    def reconcile(self, recovery_epoch: int) -> tuple[str, ...]:
        issues: list[str] = []
        for item in self.trusted_observations.values():
            snapshot = self.snapshots.get(item.quality_snapshot_id)
            if snapshot is None:
                issues.append("P40_TRUSTED_SNAPSHOT_MISSING")
            elif snapshot.trust_status != item.trust_status:
                issues.append("P40_TRUST_SNAPSHOT_DIVERGENCE")
        if any(value.trust_status is TrustStatus.TRUSTED and value.blocking_reasons for value in self.trusted_observations.values()):
            issues.append("P40_TRUSTED_WITH_BLOCKERS")
        if self.recovery_restricted or self.quality.recovery_restricted or self.reliability.recovery_restricted or self.temporal.recovery_restricted or self.safety.recovery_restricted:
            issues.append("P40_RECOVERY_RESTRICTED")
        return tuple(dict.fromkeys(issues))

    def diagnostics(self) -> dict[str, Any]:
        latest_snapshot = next(reversed(self.snapshots.values()), None) if self.snapshots else None
        latest_health = next(reversed(self.source_health.values()), None) if self.source_health else None
        return {
            "schema_version": QUALITY_TRUST_SCHEMA_VERSION,
            "schema_identity": quality_trust_schema_identity(),
            "runtime_version": DATA_QUALITY_RUNTIME_VERSION,
            "configuration_identity": self.configuration_identity,
            "trusted_observation_count": len(self.trusted_observations),
            "snapshot_count": len(self.snapshots),
            "source_health_count": len(self.source_health),
            "latest_trust_state": _snapshot_dict(latest_snapshot),
            "latest_source_health": _health_dict(latest_health),
            "recovery_restricted": self.recovery_restricted,
            "research_pipeline_active": False,
            "financial_execution_available": False,
        }

    def component_ready(self, context: Any) -> bool:
        return not self.recovery_restricted

    def component_health(self, context: Any) -> HealthStatus:
        return HealthStatus.DEGRADED if self.recovery_restricted else HealthStatus.HEALTHY

    def _envelope(self, observation, dataset_id, dataset_fingerprint, as_of, recovery_epoch, processing_mode) -> IngestionEnvelope:
        ingestion_id = deterministic_id(
            "p40_ingestion",
            observation.observation_id,
            observation.observation_fingerprint,
            dataset_id,
            dataset_fingerprint,
            observation.source.source_id,
            observation.schema_version,
            self.configuration_identity,
            recovery_epoch,
            as_of.isoformat(),
            processing_mode.value,
        )
        return IngestionEnvelope(ingestion_id, observation.observation_id, observation.observation_fingerprint, dataset_id, dataset_fingerprint, observation.source.source_id, observation.schema_version, self.configuration_identity, recovery_epoch, as_of, processing_mode.value)

    @staticmethod
    def _scope(observation: CanonicalMarketObservation, dataset_id: str) -> str:
        return "|".join((observation.source.source_id, dataset_id, observation.instrument.canonical_id, observation.timeframe))

    def _scalar(self, observation, dataset_id, dataset_fingerprint) -> ScalarObservation:
        return ScalarObservation.create(
            observation.instrument.canonical_id,
            f"{observation.timeframe}:CLOSE",
            observation.bar.close,
            observation.event_time,
            observation.available_at,
            observation.source.source_id,
            dataset_id,
            dataset_fingerprint,
            self.configuration_identity,
            ObservationHealth.HEALTHY,
        )

    def _freshness(self, observation, as_of) -> FreshnessState:
        seconds = TIMEFRAME_SECONDS.get(observation.timeframe)
        if seconds is None:
            return FreshnessState.UNKNOWN
        age = Decimal(str((as_of - observation.event_time).total_seconds()))
        if age < 0:
            return FreshnessState.UNKNOWN
        if age <= Decimal(seconds):
            return FreshnessState.FRESH
        if age <= Decimal(seconds) * self.configuration.staleness_multiplier:
            return FreshnessState.AGING
        return FreshnessState.STALE

    def _ensure_scope_engines(self, scope_id, dataset_fingerprint, as_of, recovery_epoch) -> None:
        self.reliability.initialize(scope_id, dataset_fingerprint, as_of, recovery_epoch)
        self.temporal.initialize(scope_id, dataset_fingerprint, as_of.date().isoformat(), as_of.strftime("%G-W%V"), as_of, recovery_epoch)
        self.safety.initialize(scope_id, dataset_fingerprint, as_of, recovery_epoch)

    def _process_temporal(self, scope_id, observation, dataset_fingerprint, as_of, recovery_epoch, upstream_multiplier):
        outcome = TemporalQualityOutcome.create(
            scope_id,
            "MARKET_DATA_TRUST",
            "CANONICAL_BAR",
            observation.instrument.canonical_id,
            OutcomeClass.NEUTRAL,
            Decimal("0"),
            observation.event_time.date().isoformat(),
            observation.event_time.strftime("%G-W%V"),
            observation.event_time,
            observation.available_at,
            observation.provenance.source_record_locator or observation.source.source_id,
            dataset_fingerprint,
            self.configuration_identity,
            recovery_epoch,
        )
        return self.temporal.process(outcome, as_of, upstream_multiplier)

    def _process_reliability(self, scope_id, observation, dataset_fingerprint, as_of, recovery_epoch, blockers, warnings):
        hard_blockers = self._hard_blockers(blockers)
        delta = Decimal("-20") if hard_blockers else Decimal("-2") if warnings else Decimal("0")
        outcome = QualityOutcomeDelta.create(scope_id, delta, observation.event_time, observation.available_at, observation.provenance.source_record_locator or observation.source.source_id, dataset_fingerprint, self.configuration_identity, recovery_epoch)
        return self.reliability.process(outcome, as_of)

    def _process_safety(self, scope_id, observation, dataset_fingerprint, as_of, recovery_epoch, blockers):
        hard_blockers = self._hard_blockers(blockers)
        if not hard_blockers:
            class _NoAction:
                decision = SafetyDecision.NO_ACTION
                reason_codes = ("SAFETY_NO_SIGNAL",)
                event = None
            return _NoAction()
        severity = SignalSeverity.HIGH if any(reason in hard_blockers for reason in ("IDENTITY_COLLISION", "FINGERPRINT_MISMATCH", ValidationReason.DATASET_ERROR.value)) else SignalSeverity.MEDIUM
        signal = SystemSafetySignal.create(scope_id, SafetyDomain.DATA_INTEGRITY, severity, "P40_DATA_TRUST_BLOCKED", observation.event_time, min(observation.available_at, as_of), (observation.observation_id,), dataset_fingerprint, self.configuration_identity, recovery_epoch)
        return self.safety.process(signal, as_of)

    @staticmethod
    def _hard_blockers(blockers: Iterable[str]) -> set[str]:
        soft = {
            "QUALITY_UNAVAILABLE",
            "QUALITY_BASELINE_UNAVAILABLE",
            "PROVENANCE_MISSING",
            "STALE",
        }
        return {reason for reason in blockers if reason not in soft}

    def _source_health(self, scope_id, observation, dataset_id, trust, freshness, as_of, state, blockers, warnings):
        if trust in (TrustStatus.REJECTED, TrustStatus.QUARANTINED):
            status = ContinuityState.FAILED if trust is TrustStatus.REJECTED else ContinuityState.INTERRUPTED
        elif freshness is FreshnessState.STALE:
            status = ContinuityState.STALE
        elif warnings or trust is TrustStatus.RESTRICTED:
            status = ContinuityState.INTERRUPTED
        else:
            status = ContinuityState.HEALTHY
        state.counters[trust.value.lower()] += 1
        snapshot_id = deterministic_id("p40_source_health", scope_id, status.value, state.counters, as_of.isoformat())
        health = SourceHealthSnapshot(
            snapshot_id,
            observation.source.source_id,
            dataset_id,
            scope_id,
            status,
            as_of,
            state.last_received,
            state.last_trusted,
            freshness,
            state.counters["received"],
            state.counters["trusted"] + state.counters["trusted_with_warnings"],
            state.counters["restricted"],
            state.counters["quarantined"],
            state.counters["rejected"],
            state.counters["duplicates"],
            state.counters["collisions"],
            state.counters["gaps"],
            state.counters["out_of_order"],
            blockers,
            warnings,
        )
        state.latest_health = health
        return health

    @staticmethod
    def _trust(blockers, warnings, duplicate_status, structural_status, provenance_status) -> TrustStatus:
        blocker_set = set(blockers)
        if duplicate_status == "EXACT_DUPLICATE" and not blocker_set:
            return TrustStatus.TRUSTED_WITH_WARNINGS
        if structural_status == "INVALID":
            return TrustStatus.REJECTED
        if "IDENTITY_COLLISION" in blocker_set or "SEQUENCE_REGRESSION" in blocker_set or "OUT_OF_ORDER" in blocker_set:
            return TrustStatus.QUARANTINED
        if "FUTURE_TIMESTAMP" in blocker_set:
            return TrustStatus.REJECTED
        if provenance_status != "VALID":
            return TrustStatus.RESTRICTED
        if blocker_set:
            return TrustStatus.RESTRICTED
        if warnings:
            return TrustStatus.TRUSTED_WITH_WARNINGS
        return TrustStatus.TRUSTED

    def _bound(self) -> None:
        while len(self.snapshots) > self.configuration.maximum_snapshots:
            self.snapshots.popitem(last=False)
        while len(self.trusted_observations) > self.configuration.maximum_snapshots:
            self.trusted_observations.popitem(last=False)
        while len(self.source_health) > self.configuration.maximum_snapshots:
            self.source_health.popitem(last=False)
        while len(self._processed) > self.configuration.maximum_snapshots:
            self._processed.popitem(last=False)

    def _record(self, event: str, payload: Mapping[str, Any]) -> None:
        if self.audit is not None:
            self.audit.record(event, payload)


class DataQualityRuntimeComponent:
    def __init__(self, component_id: str, runtime: DataQualityTrustRuntime | None = None) -> None:
        self.component_id = component_id
        self.runtime = runtime or DataQualityTrustRuntime()

    def initialize_component(self, context: Any) -> None:
        audit = context.services.get("audit") if hasattr(context, "services") else None
        if audit is not None:
            audit.record("data_quality_runtime_initialized", {"component_id": self.component_id, "schema_identity": quality_trust_schema_identity()})

    def component_ready(self, context: Any) -> bool:
        return self.runtime.component_ready(context)

    def component_health(self, context: Any) -> HealthStatus:
        return self.runtime.component_health(context)

    def diagnostics(self) -> dict[str, Any]:
        payload = self.runtime.diagnostics()
        payload["component_id"] = self.component_id
        return payload


def data_quality_component_registrations() -> tuple[tuple[ComponentMetadata, DataQualityRuntimeComponent], ...]:
    capabilities = ComponentCapabilities(lifecycle=True, persistence=True, recovery=True, health=True, diagnostics=True, activation=True)
    runtime = DataQualityTrustRuntime()
    return (
        (
            ComponentMetadata("observation_quality", ComponentType.RESEARCH, DATA_QUALITY_RUNTIME_VERSION, True, ("market_dataset_authority", "clock", "configuration", "audit", "observability"), capabilities),
            DataQualityRuntimeComponent("observation_quality", runtime),
        ),
        (
            ComponentMetadata("research_reliability", ComponentType.RESEARCH, DATA_QUALITY_RUNTIME_VERSION, True, ("observation_quality",), capabilities),
            DataQualityRuntimeComponent("research_reliability", runtime),
        ),
        (
            ComponentMetadata("temporal_quality", ComponentType.RESEARCH, DATA_QUALITY_RUNTIME_VERSION, True, ("observation_quality", "clock"), capabilities),
            DataQualityRuntimeComponent("temporal_quality", runtime),
        ),
        (
            ComponentMetadata("data_trust", ComponentType.RESEARCH, DATA_QUALITY_RUNTIME_VERSION, True, ("observation_quality", "research_reliability", "temporal_quality", "market_data_contract"), capabilities),
            DataQualityRuntimeComponent("data_trust", runtime),
        ),
    )


def data_quality_components_from_inventory(inventory: tuple[Mapping[str, Any], ...]) -> dict[str, Mapping[str, Any]]:
    ids = {"observation_quality", "research_reliability", "temporal_quality", "data_trust"}
    return {item["component_id"]: item for item in inventory if item.get("component_id") in ids}


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("P40_NAIVE_LOGICAL_TIME")
    return value.astimezone(timezone.utc)


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(nested) for key, nested in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {field: _jsonable(getattr(value, field)) for field in value.__dataclass_fields__}
    return value


def _snapshot_dict(snapshot: QualityTrustSnapshot | None) -> dict[str, Any] | None:
    return _jsonable(snapshot) if snapshot else None


def _health_dict(snapshot: SourceHealthSnapshot | None) -> dict[str, Any] | None:
    return _jsonable(snapshot) if snapshot else None
