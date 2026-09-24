from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from amrte.core.composition import ComponentCapabilities, ComponentMetadata, ComponentType
from amrte.core.identity import deterministic_id
from amrte.core.types import HealthStatus
from amrte.market.observation import (
    CanonicalMarketDataset,
    CanonicalMarketObservation,
    schema_identity as market_data_schema_identity,
)
from amrte.research.controlled_experimentation import (
    ConfigurationStatus,
    VERSIONED_RESEARCH_CONFIGURATION_SCHEMA_VERSION,
    VersionedResearchConfiguration,
    versioned_research_configuration_schema_identity,
)
from amrte.research.data_quality_runtime import (
    DataQualityTrustRuntime,
    TrustStatus,
    quality_trust_schema_identity,
)
from amrte.research.decision_runtime import final_research_decision_schema_identity
from amrte.research.evidence_ledger import research_decision_evidence_record_schema_identity
from amrte.research.outcome_performance import research_outcome_window_schema_identity


FORWARD_RESEARCH_RUNTIME_VERSION = "1.0"
FORWARD_RESEARCH_SESSION_SCHEMA_VERSION = "1.0"
FORWARD_OBSERVATION_ENVELOPE_SCHEMA_VERSION = "1.0"
FORWARD_RESEARCH_DECISION_RECORD_SCHEMA_VERSION = "1.0"
SHADOW_RESEARCH_COMPARISON_SCHEMA_VERSION = "1.0"
FORWARD_DRIFT_SNAPSHOT_SCHEMA_VERSION = "1.0"
FORWARD_RUNTIME_RECOVERY_SCHEMA_VERSION = "1.0"
FORWARD_RESEARCH_POLICY_VERSION = "1.0"


class ForwardSessionState(Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    RECOVERY_RESTRICTED = "RECOVERY_RESTRICTED"


class ForwardObservationEffect(Enum):
    ACCEPTED = "ACCEPTED"
    RECORDED_ONLY = "RECORDED_ONLY"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"


class SourceLifecycleState(Enum):
    INITIALIZING = "INITIALIZING"
    FORWARD_HEALTHY = "FORWARD_HEALTHY"
    FORWARD_WARNINGS = "FORWARD_WARNINGS"
    STALE = "STALE"
    GAP_DETECTED = "GAP_DETECTED"
    BACKFILL_OBSERVED = "BACKFILL_OBSERVED"
    RESTRICTED = "RESTRICTED"
    UNAVAILABLE = "UNAVAILABLE"


class ShadowComparisonState(Enum):
    MATCH = "MATCH"
    DIVERGED = "DIVERGED"
    INSUFFICIENT = "INSUFFICIENT"
    INVALID = "INVALID"


class ForwardDriftState(Enum):
    STABLE = "STABLE"
    DRIFTED = "DRIFTED"
    INSUFFICIENT = "INSUFFICIENT"
    INVALID = "INVALID"


@dataclass(frozen=True)
class ForwardResearchPolicy:
    policy_id: str
    version: str
    minimum_drift_samples: int
    default_drift_threshold: Decimal
    shadow_tolerance: Decimal
    stale_after: timedelta
    policy_identity: str

    @classmethod
    def current(cls) -> "ForwardResearchPolicy":
        payload = {
            "policy_id": "P51_FORWARD_RESEARCH_POLICY",
            "version": FORWARD_RESEARCH_POLICY_VERSION,
            "minimum_drift_samples": 3,
            "default_drift_threshold": "0.50000000",
            "shadow_tolerance": "0.00000001",
            "stale_after_seconds": 3600,
            "financial_execution": "NONE",
            "automatic_configuration_mutation": False,
        }
        return cls(
            str(payload["policy_id"]),
            str(payload["version"]),
            int(payload["minimum_drift_samples"]),
            Decimal(str(payload["default_drift_threshold"])),
            Decimal(str(payload["shadow_tolerance"])),
            timedelta(seconds=int(payload["stale_after_seconds"])),
            _sha256_json(payload),
        )


@dataclass(frozen=True)
class ForwardResearchSession:
    session_id: str
    schema_version: str
    schema_identity: str
    research_configuration_id: str
    configuration_version: str
    configuration_schema_identity: str
    configuration_fingerprint: str
    configuration_status: str
    configuration_frozen_at_utc: datetime
    promotion_decision_id: str
    approval_evidence_refs: tuple[str, ...]
    dataset_id: str
    dataset_fingerprint: str
    source_id: str
    instrument_id: str
    timeframe: str
    historical_cutoff_utc: datetime
    started_at_utc: datetime
    last_observation_at_utc: datetime | None
    last_decision_at_utc: datetime | None
    session_state: str
    source_lifecycle_state: str
    observation_count: int
    accepted_decision_count: int
    rejected_observation_count: int
    duplicate_observation_count: int
    gap_count: int
    backfill_count: int
    recovery_epoch: int
    runtime_configuration_identity: str
    session_fingerprint: str
    financial_execution: str = "NONE"
    trade_authorization: str = "NONE"


@dataclass(frozen=True)
class ForwardObservationEnvelope:
    envelope_id: str
    schema_version: str
    schema_identity: str
    session_id: str
    observation_id: str
    observation_fingerprint: str
    trusted_observation_id: str
    quality_snapshot_id: str
    source_health_snapshot_id: str
    trust_status: str
    dataset_id: str
    dataset_fingerprint: str
    source_id: str
    event_time_utc: datetime
    available_at_utc: datetime
    received_at_utc: datetime
    sequence: int | None
    logical_time_utc: datetime
    watermark_utc: datetime | None
    ingestion_order: int
    duplicate: bool
    backfill: bool
    gap_detected: bool
    effect: str
    reason_codes: tuple[str, ...]
    warning_codes: tuple[str, ...]
    p39_observation_schema_identity: str
    p40_quality_schema_identity: str
    envelope_fingerprint: str
    financial_execution: str = "NONE"


@dataclass(frozen=True)
class ForwardResearchDecisionRecord:
    decision_id: str
    schema_version: str
    schema_identity: str
    session_id: str
    envelope_id: str
    observation_id: str
    research_configuration_id: str
    configuration_fingerprint: str
    forward_signal_value: Decimal
    final_classification: str
    effective_permission: str
    knowledge_cutoff_utc: datetime
    created_at_utc: datetime
    reason_codes: tuple[str, ...]
    warning_codes: tuple[str, ...]
    p46_final_decision_schema_identity: str
    p47_evidence_record_schema_identity: str
    p48_outcome_window_schema_identity: str
    decision_fingerprint: str
    research_only: bool = True
    trade_authorization: str = "NONE"
    financial_authorization: str = "NONE"
    financial_execution: str = "NONE"


@dataclass(frozen=True)
class ShadowResearchComparison:
    comparison_id: str
    schema_version: str
    schema_identity: str
    session_id: str
    decision_id: str
    observation_id: str
    baseline_shadow_value: Decimal
    forward_signal_value: Decimal
    absolute_delta: Decimal
    tolerance: Decimal
    state: str
    compared_at_utc: datetime
    reason_codes: tuple[str, ...]
    comparison_fingerprint: str
    financial_execution: str = "NONE"


@dataclass(frozen=True)
class ForwardDriftSnapshot:
    drift_snapshot_id: str
    schema_version: str
    schema_identity: str
    session_id: str
    dimension: str
    baseline_mean: Decimal
    forward_mean: Decimal
    absolute_delta: Decimal
    threshold: Decimal
    sample_count: int
    state: str
    as_of_utc: datetime
    reason_codes: tuple[str, ...]
    snapshot_fingerprint: str
    financial_execution: str = "NONE"


@dataclass(frozen=True)
class ForwardRuntimeRecoveryState:
    schema_version: str
    runtime_version: str
    policy_identity: str
    configuration_identity: str
    recovery_epoch: int
    session_schema_identity: str
    envelope_schema_identity: str
    decision_schema_identity: str
    shadow_schema_identity: str
    drift_schema_identity: str
    sessions: tuple[ForwardResearchSession, ...]
    envelopes: tuple[ForwardObservationEnvelope, ...]
    decisions: tuple[ForwardResearchDecisionRecord, ...]
    shadow_comparisons: tuple[ShadowResearchComparison, ...]
    drift_snapshots: tuple[ForwardDriftSnapshot, ...]
    replay_fingerprint: str


class ForwardResearchRuntime:
    """Forward-only research observation runtime.

    P51 observes approved research configurations in forward time. It records
    research evidence only and deliberately contains no execution, brokerage,
    account, order, or capital authority.
    """

    def __init__(
        self,
        *,
        clock: Any,
        audit: Any,
        data_quality_runtime: DataQualityTrustRuntime | None = None,
        policy: ForwardResearchPolicy | None = None,
        configuration_identity: str = "P51_FORWARD_RESEARCH_RUNTIME_DEFAULT",
        storage_root: Path = Path("data/forward-research-runtime"),
        maximum_sessions: int = 512,
        maximum_observations: int = 50_000,
        maximum_decisions: int = 50_000,
        maximum_query_limit: int = 100,
    ) -> None:
        self.clock = clock
        self.audit = audit
        self.data_quality = data_quality_runtime or DataQualityTrustRuntime(audit=audit)
        self.policy = policy or ForwardResearchPolicy.current()
        self.configuration_identity = configuration_identity
        self.storage_root = Path(storage_root)
        self.maximum_sessions = max(1, maximum_sessions)
        self.maximum_observations = max(1, maximum_observations)
        self.maximum_decisions = max(1, maximum_decisions)
        self.maximum_query_limit = max(1, min(maximum_query_limit, 500))
        self.sessions: OrderedDict[str, ForwardResearchSession] = OrderedDict()
        self.envelopes: OrderedDict[str, ForwardObservationEnvelope] = OrderedDict()
        self.decisions: OrderedDict[str, ForwardResearchDecisionRecord] = OrderedDict()
        self.shadow_comparisons: OrderedDict[str, ShadowResearchComparison] = OrderedDict()
        self.drift_snapshots: OrderedDict[str, ForwardDriftSnapshot] = OrderedDict()
        self._watermarks: dict[str, datetime] = {}
        self._last_sequence: dict[str, int] = {}
        self._observation_fingerprints: dict[str, str] = {}
        self.recovery_restricted = False
        self.metrics = {
            "sessions_started": 0,
            "observations_recorded": 0,
            "decisions_recorded": 0,
            "duplicates": 0,
            "gaps": 0,
            "backfills": 0,
            "rejections": 0,
            "shadow_matches": 0,
            "shadow_divergences": 0,
            "drift_snapshots": 0,
            "recovery_count": 0,
            "recovery_failures": 0,
        }
        self.initialize_component(None)

    def initialize_component(self, context: Any) -> None:
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self._record(
            "forward_research_runtime_initialized",
            {
                "policy_identity": self.policy.policy_identity,
                "configuration_identity": self.configuration_identity,
            },
        )

    def start_session(
        self,
        configuration: VersionedResearchConfiguration,
        dataset: CanonicalMarketDataset,
        *,
        historical_cutoff_utc: datetime,
        source_id: str | None = None,
        as_of: datetime | None = None,
        recovery_epoch: int = 0,
    ) -> ForwardResearchSession:
        now = _aware_utc(as_of or self.clock.now())
        cutoff = _aware_utc(historical_cutoff_utc)
        reasons = self.validate_configuration(configuration)
        if reasons:
            raise ValueError(";".join(reasons))
        dataset_validation = dataset.verify()
        if not dataset_validation.valid:
            raise ValueError("P51_DATASET_MANIFEST_INVALID")
        manifest = dataset.manifest
        selected_source = source_id or (manifest.source_ids[0] if manifest.source_ids else "UNKNOWN_SOURCE")
        if source_id is not None and source_id not in manifest.source_ids:
            raise ValueError("P51_SOURCE_NOT_IN_DATASET")
        instrument_id = manifest.instruments[0] if len(manifest.instruments) == 1 else "MULTI_INSTRUMENT"
        timeframe = manifest.timeframes[0] if len(manifest.timeframes) == 1 else "MULTI_TIMEFRAME"
        fingerprint = _sha256_json(
            {
                "configuration": configuration.research_configuration_id,
                "configuration_fingerprint": configuration.configuration_fingerprint,
                "dataset": manifest.dataset_fingerprint,
                "source": selected_source,
                "instrument": instrument_id,
                "timeframe": timeframe,
                "cutoff": cutoff,
                "recovery_epoch": recovery_epoch,
                "policy": self.policy.policy_identity,
            }
        )
        session_id = deterministic_id("p51_forward_research_session", fingerprint)
        existing = self.sessions.get(session_id)
        if existing is not None:
            return existing
        session = ForwardResearchSession(
            session_id,
            FORWARD_RESEARCH_SESSION_SCHEMA_VERSION,
            forward_research_session_schema_identity(),
            configuration.research_configuration_id,
            configuration.configuration_version,
            configuration.schema_identity,
            configuration.configuration_fingerprint,
            configuration.status,
            now,
            configuration.promotion_decision_id,
            tuple(configuration.approval_evidence_refs),
            manifest.dataset_id,
            manifest.dataset_fingerprint,
            selected_source,
            instrument_id,
            timeframe,
            cutoff,
            now,
            None,
            None,
            ForwardSessionState.RUNNING.value,
            SourceLifecycleState.INITIALIZING.value,
            0,
            0,
            0,
            0,
            0,
            0,
            recovery_epoch,
            self.configuration_identity,
            fingerprint,
        )
        self.sessions[session.session_id] = session
        self._trim(self.sessions, self.maximum_sessions)
        self.metrics["sessions_started"] += 1
        self._record("forward_research_session_started", {"session_id": session.session_id})
        return session

    def validate_configuration(self, configuration: VersionedResearchConfiguration) -> tuple[str, ...]:
        reasons: list[str] = []
        if configuration.schema_version != VERSIONED_RESEARCH_CONFIGURATION_SCHEMA_VERSION:
            reasons.append("P51_P50_CONFIGURATION_SCHEMA_VERSION_MISMATCH")
        if configuration.schema_identity != versioned_research_configuration_schema_identity():
            reasons.append("P51_P50_CONFIGURATION_SCHEMA_IDENTITY_MISMATCH")
        if configuration.status != ConfigurationStatus.APPROVED_RESEARCH.value:
            reasons.append("P51_CONFIGURATION_NOT_APPROVED_RESEARCH")
        if not configuration.configuration_fingerprint:
            reasons.append("P51_CONFIGURATION_FINGERPRINT_MISSING")
        if configuration.financial_execution != "NONE":
            reasons.append("P51_FINANCIAL_EXECUTION_FORBIDDEN")
        return tuple(dict.fromkeys(reasons))

    def ingest_observation(
        self,
        session_id: str,
        observation: CanonicalMarketObservation,
        *,
        dataset: CanonicalMarketDataset,
        logical_time: datetime | None = None,
        baseline_shadow_value: Decimal | int | float | str | None = None,
        recovery_epoch: int = 0,
    ) -> tuple[ForwardObservationEnvelope, ForwardResearchDecisionRecord | None]:
        if self.recovery_restricted:
            raise ValueError("P51_RECOVERY_RESTRICTED")
        session = self.sessions[session_id]
        if session.session_state != ForwardSessionState.RUNNING.value:
            raise ValueError("P51_SESSION_NOT_RUNNING")
        now = _aware_utc(logical_time or observation.received_at)
        reasons: list[str] = []
        warnings: list[str] = []
        if dataset.manifest.dataset_fingerprint != session.dataset_fingerprint:
            reasons.append("P51_DATASET_FINGERPRINT_MISMATCH")
        if observation.source.source_id != session.source_id:
            reasons.append("P51_SOURCE_MISMATCH")
        if observation.instrument.canonical_id != session.instrument_id and session.instrument_id != "MULTI_INSTRUMENT":
            reasons.append("P51_INSTRUMENT_MISMATCH")
        if observation.timeframe != session.timeframe and session.timeframe != "MULTI_TIMEFRAME":
            reasons.append("P51_TIMEFRAME_MISMATCH")
        if observation.event_time <= session.historical_cutoff_utc:
            reasons.append("P51_NOT_FORWARD_OBSERVATION")
        if now - observation.available_at > self.policy.stale_after:
            warnings.append("P51_SOURCE_STALE")
        previous_watermark = self._watermarks.get(session_id)
        backfill = previous_watermark is not None and observation.event_time < previous_watermark
        if backfill:
            warnings.append("P51_BACKFILL_OBSERVED")
        previous_sequence = self._last_sequence.get(session_id)
        gap = False
        if observation.sequence is not None and previous_sequence is not None and observation.sequence > previous_sequence + 1:
            gap = True
            warnings.append("P51_SEQUENCE_GAP")
        trusted = self.data_quality.ingest_observation(
            observation,
            dataset=dataset,
            logical_time=now,
            recovery_epoch=recovery_epoch,
        )
        if trusted.blocking_reasons:
            reasons.extend(f"P40_{item}" for item in trusted.blocking_reasons)
        warnings.extend(f"P40_{item}" for item in trusted.warning_reasons)
        duplicate = self._already_recorded_observation(observation)
        if duplicate:
            effect = ForwardObservationEffect.DUPLICATE
        elif reasons or trusted.trust_status in (TrustStatus.REJECTED, TrustStatus.QUARANTINED):
            effect = ForwardObservationEffect.REJECTED
        elif trusted.trust_status in (TrustStatus.TRUSTED, TrustStatus.TRUSTED_WITH_WARNINGS):
            effect = ForwardObservationEffect.ACCEPTED
        else:
            effect = ForwardObservationEffect.RECORDED_ONLY
        envelope = self._envelope(
            session,
            observation,
            trusted,
            logical_time=now,
            watermark=previous_watermark,
            ingestion_order=len(self.envelopes) + 1,
            duplicate=duplicate,
            backfill=backfill,
            gap_detected=gap,
            effect=effect,
            reason_codes=tuple(dict.fromkeys(reasons)),
            warning_codes=tuple(dict.fromkeys(warnings)),
        )
        self.envelopes[envelope.envelope_id] = envelope
        self._observation_fingerprints.setdefault(observation.observation_id, observation.observation_fingerprint)
        self._trim(self.envelopes, self.maximum_observations)
        decision: ForwardResearchDecisionRecord | None = None
        if effect is ForwardObservationEffect.ACCEPTED:
            decision = self._decision(session, envelope, observation, now)
            self.decisions[decision.decision_id] = decision
            self._trim(self.decisions, self.maximum_decisions)
            self.metrics["decisions_recorded"] += 1
            if baseline_shadow_value is not None:
                self.compare_shadow_decision(decision.decision_id, baseline_shadow_value, as_of=now)
        self._update_session(session_id, envelope, decision)
        self.metrics["observations_recorded"] += 1
        if duplicate:
            self.metrics["duplicates"] += 1
        if gap:
            self.metrics["gaps"] += 1
        if backfill:
            self.metrics["backfills"] += 1
        if effect is ForwardObservationEffect.REJECTED:
            self.metrics["rejections"] += 1
        self._record("forward_observation_recorded", {"session_id": session_id, "effect": effect.value})
        return envelope, decision

    def compare_shadow_decision(
        self,
        decision_id: str,
        baseline_shadow_value: Decimal | int | float | str,
        *,
        tolerance: Decimal | int | float | str | None = None,
        as_of: datetime | None = None,
    ) -> ShadowResearchComparison:
        decision = self.decisions[decision_id]
        baseline = _decimal(baseline_shadow_value)
        allowed = self.policy.shadow_tolerance if tolerance is None else _decimal(tolerance)
        delta = abs(decision.forward_signal_value - baseline)
        if allowed < Decimal("0"):
            state = ShadowComparisonState.INVALID
            reasons = ("P51_SHADOW_TOLERANCE_INVALID",)
        elif delta <= allowed:
            state = ShadowComparisonState.MATCH
            reasons = ("P51_SHADOW_MATCH",)
        else:
            state = ShadowComparisonState.DIVERGED
            reasons = ("P51_SHADOW_DIVERGENCE",)
        fingerprint = _sha256_json(
            {
                "decision": decision.decision_id,
                "baseline": baseline,
                "forward": decision.forward_signal_value,
                "delta": delta,
                "tolerance": allowed,
                "state": state.value,
            }
        )
        comparison = ShadowResearchComparison(
            deterministic_id("p51_shadow_research_comparison", fingerprint),
            SHADOW_RESEARCH_COMPARISON_SCHEMA_VERSION,
            shadow_research_comparison_schema_identity(),
            decision.session_id,
            decision.decision_id,
            decision.observation_id,
            baseline,
            decision.forward_signal_value,
            delta,
            allowed,
            state.value,
            _aware_utc(as_of or self.clock.now()),
            reasons,
            fingerprint,
        )
        self.shadow_comparisons[comparison.comparison_id] = comparison
        if state is ShadowComparisonState.MATCH:
            self.metrics["shadow_matches"] += 1
        elif state is ShadowComparisonState.DIVERGED:
            self.metrics["shadow_divergences"] += 1
        return comparison

    def detect_drift(
        self,
        session_id: str,
        baseline_mean: Decimal | int | float | str,
        *,
        threshold: Decimal | int | float | str | None = None,
        as_of: datetime | None = None,
    ) -> ForwardDriftSnapshot:
        baseline = _decimal(baseline_mean)
        limit = self.policy.default_drift_threshold if threshold is None else _decimal(threshold)
        values = tuple(
            item.forward_signal_value
            for item in self.decisions.values()
            if item.session_id == session_id
        )
        reasons: tuple[str, ...]
        if limit < Decimal("0"):
            forward = Decimal("0")
            delta = Decimal("0")
            state = ForwardDriftState.INVALID
            reasons = ("P51_DRIFT_THRESHOLD_INVALID",)
        elif len(values) < self.policy.minimum_drift_samples:
            forward = Decimal("0")
            delta = Decimal("0")
            state = ForwardDriftState.INSUFFICIENT
            reasons = ("P51_DRIFT_SAMPLE_INSUFFICIENT",)
        else:
            forward = _q(sum(values, Decimal("0")) / Decimal(len(values)))
            delta = abs(forward - baseline)
            state = ForwardDriftState.DRIFTED if delta > limit else ForwardDriftState.STABLE
            reasons = (f"P51_DRIFT_{state.value}",)
        fingerprint = _sha256_json(
            {
                "session": session_id,
                "baseline": baseline,
                "forward": forward,
                "threshold": limit,
                "sample_count": len(values),
                "state": state.value,
            }
        )
        snapshot = ForwardDriftSnapshot(
            deterministic_id("p51_forward_drift_snapshot", fingerprint),
            FORWARD_DRIFT_SNAPSHOT_SCHEMA_VERSION,
            forward_drift_snapshot_schema_identity(),
            session_id,
            "FORWARD_SIGNAL_VALUE",
            baseline,
            forward,
            delta,
            limit,
            len(values),
            state.value,
            _aware_utc(as_of or self.clock.now()),
            reasons,
            fingerprint,
        )
        self.drift_snapshots[snapshot.drift_snapshot_id] = snapshot
        self.metrics["drift_snapshots"] += 1
        return snapshot

    def query_sessions(self, *, offset: int = 0, limit: int = 50) -> tuple[ForwardResearchSession, ...]:
        bounded = max(1, min(limit, self.maximum_query_limit))
        return tuple(self.sessions.values())[max(0, offset) : max(0, offset) + bounded]

    def query_envelopes(self, session_id: str | None = None, *, offset: int = 0, limit: int = 50) -> tuple[ForwardObservationEnvelope, ...]:
        bounded = max(1, min(limit, self.maximum_query_limit))
        items = tuple(item for item in self.envelopes.values() if session_id is None or item.session_id == session_id)
        return items[max(0, offset) : max(0, offset) + bounded]

    def query_shadow_comparisons(self, session_id: str | None = None, *, offset: int = 0, limit: int = 50) -> tuple[ShadowResearchComparison, ...]:
        bounded = max(1, min(limit, self.maximum_query_limit))
        items = tuple(item for item in self.shadow_comparisons.values() if session_id is None or item.session_id == session_id)
        return items[max(0, offset) : max(0, offset) + bounded]

    def recovery_state(self, recovery_epoch: int) -> ForwardRuntimeRecoveryState:
        return ForwardRuntimeRecoveryState(
            FORWARD_RUNTIME_RECOVERY_SCHEMA_VERSION,
            FORWARD_RESEARCH_RUNTIME_VERSION,
            self.policy.policy_identity,
            self.configuration_identity,
            recovery_epoch,
            forward_research_session_schema_identity(),
            forward_observation_envelope_schema_identity(),
            forward_research_decision_record_schema_identity(),
            shadow_research_comparison_schema_identity(),
            forward_drift_snapshot_schema_identity(),
            tuple(self.sessions.values()),
            tuple(self.envelopes.values()),
            tuple(self.decisions.values()),
            tuple(self.shadow_comparisons.values()),
            tuple(self.drift_snapshots.values()),
            self.replay_fingerprint(),
        )

    def restore(self, state: ForwardRuntimeRecoveryState, expected_recovery_epoch: int) -> bool:
        self.metrics["recovery_count"] += 1
        if (
            state.schema_version != FORWARD_RUNTIME_RECOVERY_SCHEMA_VERSION
            or state.runtime_version != FORWARD_RESEARCH_RUNTIME_VERSION
            or state.policy_identity != self.policy.policy_identity
            or state.configuration_identity != self.configuration_identity
            or state.recovery_epoch != expected_recovery_epoch
            or state.session_schema_identity != forward_research_session_schema_identity()
            or state.envelope_schema_identity != forward_observation_envelope_schema_identity()
            or state.decision_schema_identity != forward_research_decision_record_schema_identity()
            or state.shadow_schema_identity != shadow_research_comparison_schema_identity()
            or state.drift_schema_identity != forward_drift_snapshot_schema_identity()
        ):
            self.recovery_restricted = True
            self.metrics["recovery_failures"] += 1
            return False
        try:
            self.sessions = OrderedDict((item.session_id, item) for item in state.sessions)
            self.envelopes = OrderedDict((item.envelope_id, item) for item in state.envelopes)
            self.decisions = OrderedDict((item.decision_id, item) for item in state.decisions)
            self.shadow_comparisons = OrderedDict((item.comparison_id, item) for item in state.shadow_comparisons)
            self.drift_snapshots = OrderedDict((item.drift_snapshot_id, item) for item in state.drift_snapshots)
            if len(self.sessions) != len(state.sessions) or len(self.envelopes) != len(state.envelopes):
                raise ValueError("P51_RECOVERY_DUPLICATE_IDENTITY")
            if any(item.session_id not in self.sessions for item in self.envelopes.values()):
                raise ValueError("P51_RECOVERY_ORPHAN_ENVELOPE")
            if any(item.envelope_id not in self.envelopes for item in self.decisions.values()):
                raise ValueError("P51_RECOVERY_ORPHAN_DECISION")
            self._watermarks = {
                session_id: max(item.event_time_utc for item in envelopes)
                for session_id, envelopes in _group_envelopes_by_session(self.envelopes.values()).items()
                if envelopes
            }
            self._last_sequence = {
                session_id: max(item.sequence for item in envelopes if item.sequence is not None)
                for session_id, envelopes in _group_envelopes_by_session(self.envelopes.values()).items()
                if any(item.sequence is not None for item in envelopes)
            }
            self._observation_fingerprints = {}
            for envelope in self.envelopes.values():
                self._observation_fingerprints.setdefault(envelope.observation_id, envelope.observation_fingerprint)
            self.recovery_restricted = False
            return state.replay_fingerprint == self.replay_fingerprint()
        except Exception:
            self.recovery_restricted = True
            self.metrics["recovery_failures"] += 1
            return False

    def replay_fingerprint(self) -> str:
        return deterministic_id(
            "p51_forward_research_runtime_replay",
            self.policy.policy_identity,
            self.configuration_identity,
            *self.sessions.values(),
            *self.envelopes.values(),
            *self.decisions.values(),
            *self.shadow_comparisons.values(),
            *self.drift_snapshots.values(),
        )

    def diagnostics(self) -> dict[str, Any]:
        return {
            "runtime_version": FORWARD_RESEARCH_RUNTIME_VERSION,
            "policy_identity": self.policy.policy_identity,
            "configuration_identity": self.configuration_identity,
            "schemas": {
                "forward_research_session": forward_research_session_schema_identity(),
                "forward_observation_envelope": forward_observation_envelope_schema_identity(),
                "forward_research_decision_record": forward_research_decision_record_schema_identity(),
                "shadow_research_comparison": shadow_research_comparison_schema_identity(),
                "forward_drift_snapshot": forward_drift_snapshot_schema_identity(),
            },
            "upstream_schema_identities": {
                "p39_observation": _p39_observation_schema_identity(),
                "p40_quality_trust": _p40_quality_schema_identity(),
                "p46_final_decision": _p46_final_decision_schema_identity(),
                "p47_evidence_record": _p47_evidence_record_schema_identity(),
                "p48_outcome_window": _p48_outcome_window_schema_identity(),
                "p50_versioned_research_configuration": _p50_versioned_configuration_schema_identity(),
            },
            "session_count": len(self.sessions),
            "observation_envelope_count": len(self.envelopes),
            "decision_count": len(self.decisions),
            "shadow_comparison_count": len(self.shadow_comparisons),
            "drift_snapshot_count": len(self.drift_snapshots),
            "latest_session": _session_summary(next(reversed(self.sessions.values()), None) if self.sessions else None),
            "metrics": dict(self.metrics),
            "recovery_restricted": self.recovery_restricted,
            "research_only": True,
            "configuration_mutation": "PROHIBITED",
            "automatic_retuning": "PROHIBITED",
            "trade_authorization": "NONE",
            "financial_authorization": "NONE",
            "financial_execution": "NONE",
        }

    def component_ready(self, context: Any) -> bool:
        return not self.recovery_restricted

    def component_health(self, context: Any) -> HealthStatus:
        return HealthStatus.RESTRICTED if self.recovery_restricted else HealthStatus.HEALTHY

    def _envelope(
        self,
        session: ForwardResearchSession,
        observation: CanonicalMarketObservation,
        trusted: Any,
        *,
        logical_time: datetime,
        watermark: datetime | None,
        ingestion_order: int,
        duplicate: bool,
        backfill: bool,
        gap_detected: bool,
        effect: ForwardObservationEffect,
        reason_codes: tuple[str, ...],
        warning_codes: tuple[str, ...],
    ) -> ForwardObservationEnvelope:
        fingerprint = _sha256_json(
            {
                "session": session.session_id,
                "observation": observation.observation_id,
                "fingerprint": observation.observation_fingerprint,
                "trusted": trusted.trusted_observation_id,
                "logical_time": logical_time,
                "order": ingestion_order,
                "effect": effect.value,
                "reasons": reason_codes,
                "warnings": warning_codes,
            }
        )
        return ForwardObservationEnvelope(
            deterministic_id("p51_forward_observation_envelope", fingerprint),
            FORWARD_OBSERVATION_ENVELOPE_SCHEMA_VERSION,
            forward_observation_envelope_schema_identity(),
            session.session_id,
            observation.observation_id,
            observation.observation_fingerprint,
            trusted.trusted_observation_id,
            trusted.quality_snapshot_id,
            trusted.source_health_snapshot_id,
            trusted.trust_status.value,
            session.dataset_id,
            session.dataset_fingerprint,
            observation.source.source_id,
            observation.event_time,
            observation.available_at,
            observation.received_at,
            observation.sequence,
            logical_time,
            watermark,
            ingestion_order,
            duplicate,
            backfill,
            gap_detected,
            effect.value,
            reason_codes,
            warning_codes,
            _p39_observation_schema_identity(),
            _p40_quality_schema_identity(),
            fingerprint,
        )

    def _decision(
        self,
        session: ForwardResearchSession,
        envelope: ForwardObservationEnvelope,
        observation: CanonicalMarketObservation,
        created_at: datetime,
    ) -> ForwardResearchDecisionRecord:
        value = _q(observation.bar.close)
        reasons = (
            "P51_FORWARD_RESEARCH_DECISION_OBSERVED",
            "P51_RESEARCH_ONLY_NO_FINANCIAL_AUTHORIZATION",
        )
        fingerprint = _sha256_json(
            {
                "session": session.session_id,
                "envelope": envelope.envelope_id,
                "configuration": session.research_configuration_id,
                "configuration_fingerprint": session.configuration_fingerprint,
                "value": value,
                "knowledge_cutoff": observation.available_at,
            }
        )
        return ForwardResearchDecisionRecord(
            deterministic_id("p51_forward_research_decision", fingerprint),
            FORWARD_RESEARCH_DECISION_RECORD_SCHEMA_VERSION,
            forward_research_decision_record_schema_identity(),
            session.session_id,
            envelope.envelope_id,
            observation.observation_id,
            session.research_configuration_id,
            session.configuration_fingerprint,
            value,
            "FORWARD_OBSERVED_RESEARCH",
            "RESEARCH_ONLY",
            observation.available_at,
            created_at,
            reasons,
            envelope.warning_codes,
            _p46_final_decision_schema_identity(),
            _p47_evidence_record_schema_identity(),
            _p48_outcome_window_schema_identity(),
            fingerprint,
        )

    def _update_session(
        self,
        session_id: str,
        envelope: ForwardObservationEnvelope,
        decision: ForwardResearchDecisionRecord | None,
    ) -> None:
        previous = self.sessions[session_id]
        lifecycle = self._source_lifecycle(envelope)
        last_observation = envelope.event_time_utc
        if envelope.effect in {ForwardObservationEffect.ACCEPTED.value, ForwardObservationEffect.RECORDED_ONLY.value}:
            current = self._watermarks.get(session_id)
            self._watermarks[session_id] = last_observation if current is None else max(current, last_observation)
            if envelope.sequence is not None:
                self._last_sequence[session_id] = max(self._last_sequence.get(session_id, envelope.sequence), envelope.sequence)
        self.sessions[session_id] = replace(
            previous,
            last_observation_at_utc=last_observation,
            last_decision_at_utc=decision.created_at_utc if decision else previous.last_decision_at_utc,
            source_lifecycle_state=lifecycle.value,
            observation_count=previous.observation_count + 1,
            accepted_decision_count=previous.accepted_decision_count + (1 if decision else 0),
            rejected_observation_count=previous.rejected_observation_count + (1 if envelope.effect == ForwardObservationEffect.REJECTED.value else 0),
            duplicate_observation_count=previous.duplicate_observation_count + (1 if envelope.duplicate else 0),
            gap_count=previous.gap_count + (1 if envelope.gap_detected else 0),
            backfill_count=previous.backfill_count + (1 if envelope.backfill else 0),
        )

    def _source_lifecycle(self, envelope: ForwardObservationEnvelope) -> SourceLifecycleState:
        if envelope.effect == ForwardObservationEffect.REJECTED.value:
            return SourceLifecycleState.RESTRICTED
        if envelope.backfill:
            return SourceLifecycleState.BACKFILL_OBSERVED
        if envelope.gap_detected:
            return SourceLifecycleState.GAP_DETECTED
        if "P51_SOURCE_STALE" in envelope.warning_codes or "P40_STALE" in envelope.warning_codes:
            return SourceLifecycleState.STALE
        if envelope.warning_codes:
            return SourceLifecycleState.FORWARD_WARNINGS
        if envelope.effect == ForwardObservationEffect.ACCEPTED.value:
            return SourceLifecycleState.FORWARD_HEALTHY
        return SourceLifecycleState.INITIALIZING

    def _already_recorded_observation(self, observation: CanonicalMarketObservation) -> bool:
        return self._observation_fingerprints.get(observation.observation_id) == observation.observation_fingerprint

    @staticmethod
    def _trim(items: OrderedDict[str, Any], maximum: int) -> None:
        while len(items) > maximum:
            items.popitem(last=False)

    def _record(self, event: str, payload: Mapping[str, Any]) -> None:
        if self.audit is not None:
            self.audit.record(event, dict(payload))


class ForwardResearchRuntimeComponent:
    def __init__(
        self,
        component_id: str,
        runtime_holder: dict[str, ForwardResearchRuntime] | None = None,
        *,
        data_quality_runtime: DataQualityTrustRuntime | None = None,
    ) -> None:
        self.component_id = component_id
        self.runtime: ForwardResearchRuntime | None = None
        self._runtime_holder = runtime_holder
        self._data_quality_runtime = data_quality_runtime

    def initialize_component(self, context: Any) -> None:
        if self.runtime is None:
            if self._runtime_holder is not None and "runtime" in self._runtime_holder:
                self.runtime = self._runtime_holder["runtime"]
            else:
                self.runtime = ForwardResearchRuntime(
                    clock=context.services["clock"],
                    audit=context.services["audit"],
                    data_quality_runtime=self._data_quality_runtime,
                )
                if self._runtime_holder is not None:
                    self._runtime_holder["runtime"] = self.runtime
        self.runtime.initialize_component(context)

    def component_ready(self, context: Any) -> bool:
        return self.runtime is not None and self.runtime.component_ready(context)

    def component_health(self, context: Any) -> HealthStatus:
        return self.runtime.component_health(context) if self.runtime is not None else HealthStatus.UNKNOWN

    def diagnostics(self) -> dict[str, Any]:
        payload = self.runtime.diagnostics() if self.runtime is not None else {}
        payload["component_id"] = self.component_id
        return payload

    def shutdown_component(self, context: Any) -> None:
        return None

    def snapshot_component_state(self, context: Any) -> Mapping[str, Any]:
        return {"component_id": self.component_id, "replay_fingerprint": self.runtime.replay_fingerprint() if self.runtime else None}

    def restore_component_state(self, payload: Mapping[str, Any] | None, context: Any) -> None:
        return None

    def reconcile_component(self, context: Any) -> bool:
        return True


def forward_research_component_registrations(
    *,
    data_quality_runtime: DataQualityTrustRuntime | None = None,
) -> tuple[tuple[ComponentMetadata, ForwardResearchRuntimeComponent], ...]:
    holder: dict[str, ForwardResearchRuntime] = {}
    capabilities = ComponentCapabilities(lifecycle=True, persistence=True, recovery=True, health=True, diagnostics=True, activation=True)
    definitions = (
        ("forward_observation_stream", ("versioned_research_configuration", "data_trust", "market_data_contract")),
        ("forward_session_registry", ("forward_observation_stream",)),
        ("forward_research_runtime", ("forward_session_registry", "master_research_decision", "research_evidence_ledger", "research_performance_snapshot")),
        ("shadow_research_comparison", ("forward_research_runtime",)),
        ("forward_drift_monitor", ("shadow_research_comparison",)),
        ("forward_runtime_recovery", ("forward_drift_monitor", "state")),
    )
    return tuple(
        (
            ComponentMetadata(component_id, ComponentType.RESEARCH, FORWARD_RESEARCH_RUNTIME_VERSION, True, dependencies, capabilities),
            ForwardResearchRuntimeComponent(component_id, holder, data_quality_runtime=data_quality_runtime),
        )
        for component_id, dependencies in definitions
    )


def forward_research_components_from_inventory(inventory: tuple[Mapping[str, Any], ...]) -> dict[str, dict[str, Any]]:
    ids = {
        "forward_observation_stream",
        "forward_session_registry",
        "forward_research_runtime",
        "shadow_research_comparison",
        "forward_drift_monitor",
        "forward_runtime_recovery",
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


def forward_research_policy_identity() -> str:
    return ForwardResearchPolicy.current().policy_identity


@lru_cache(maxsize=None)
def forward_research_session_schema_identity() -> str:
    return _sha256_json({"schema": "p51_forward_research_session", "version": FORWARD_RESEARCH_SESSION_SCHEMA_VERSION, "fields": tuple(ForwardResearchSession.__dataclass_fields__), "p50_configuration": _p50_versioned_configuration_schema_identity()})


@lru_cache(maxsize=None)
def forward_observation_envelope_schema_identity() -> str:
    return _sha256_json({"schema": "p51_forward_observation_envelope", "version": FORWARD_OBSERVATION_ENVELOPE_SCHEMA_VERSION, "fields": tuple(ForwardObservationEnvelope.__dataclass_fields__), "p39": _p39_observation_schema_identity(), "p40": _p40_quality_schema_identity()})


@lru_cache(maxsize=None)
def forward_research_decision_record_schema_identity() -> str:
    return _sha256_json({"schema": "p51_forward_research_decision_record", "version": FORWARD_RESEARCH_DECISION_RECORD_SCHEMA_VERSION, "fields": tuple(ForwardResearchDecisionRecord.__dataclass_fields__), "session": forward_research_session_schema_identity(), "p46": _p46_final_decision_schema_identity(), "p47": _p47_evidence_record_schema_identity(), "p48": _p48_outcome_window_schema_identity()})


@lru_cache(maxsize=None)
def shadow_research_comparison_schema_identity() -> str:
    return _sha256_json({"schema": "p51_shadow_research_comparison", "version": SHADOW_RESEARCH_COMPARISON_SCHEMA_VERSION, "fields": tuple(ShadowResearchComparison.__dataclass_fields__), "decision_record": forward_research_decision_record_schema_identity()})


@lru_cache(maxsize=None)
def forward_drift_snapshot_schema_identity() -> str:
    return _sha256_json({"schema": "p51_forward_drift_snapshot", "version": FORWARD_DRIFT_SNAPSHOT_SCHEMA_VERSION, "fields": tuple(ForwardDriftSnapshot.__dataclass_fields__), "shadow": shadow_research_comparison_schema_identity()})


@lru_cache(maxsize=None)
def _p39_observation_schema_identity() -> str:
    return market_data_schema_identity("observation")


@lru_cache(maxsize=None)
def _p40_quality_schema_identity() -> str:
    return quality_trust_schema_identity()


@lru_cache(maxsize=None)
def _p46_final_decision_schema_identity() -> str:
    return final_research_decision_schema_identity()


@lru_cache(maxsize=None)
def _p47_evidence_record_schema_identity() -> str:
    return research_decision_evidence_record_schema_identity()


@lru_cache(maxsize=None)
def _p48_outcome_window_schema_identity() -> str:
    return research_outcome_window_schema_identity()


@lru_cache(maxsize=None)
def _p50_versioned_configuration_schema_identity() -> str:
    return versioned_research_configuration_schema_identity()


def _session_summary(session: ForwardResearchSession | None) -> dict[str, Any] | None:
    if session is None:
        return None
    return {
        "session_id": session.session_id,
        "research_configuration_id": session.research_configuration_id,
        "dataset_id": session.dataset_id,
        "source_id": session.source_id,
        "session_state": session.session_state,
        "source_lifecycle_state": session.source_lifecycle_state,
        "observation_count": session.observation_count,
        "accepted_decision_count": session.accepted_decision_count,
        "financial_execution": session.financial_execution,
    }


def _group_envelopes_by_session(envelopes: Any) -> dict[str, tuple[ForwardObservationEnvelope, ...]]:
    grouped: dict[str, tuple[ForwardObservationEnvelope, ...]] = {}
    for envelope in envelopes:
        grouped[envelope.session_id] = (*grouped.get(envelope.session_id, ()), envelope)
    return grouped


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("P51_NAIVE_TIMESTAMP")
    return value.astimezone(timezone.utc)


def _decimal(value: Decimal | int | float | str) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("P51_NONFINITE_DECIMAL")
    return _q(result)


def _q(value: Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.00000001"))


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, timedelta):
        return int(value.total_seconds())
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
