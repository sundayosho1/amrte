"""Point-in-time-safe quality analysis for neutral scalar observations.

This module deliberately models generic observations and research admission.
It contains no market, instrument, price, order, account, or execution concepts.
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
from enum import Enum, auto
from statistics import median
from threading import RLock

from amrte.core.identity import deterministic_id
from amrte.core.observability_types import (
    DecisionEvaluation,
    DecisionOutcome,
    DecisionStatus,
    DecisionTrace,
)


QUALITY_ENGINE_VERSION = "1.0"
QUALITY_RECOVERY_SCHEMA_VERSION = "1.0"
ZERO = Decimal("0")
ONE = Decimal("1")


class ObservationHealth(Enum):
    HEALTHY = auto()
    DEGRADED = auto()
    STALE = auto()
    INVALID = auto()
    UNAVAILABLE = auto()
    UNKNOWN = auto()


class DeviationRegime(Enum):
    NORMAL = auto()
    ELEVATED = auto()
    HIGH = auto()
    EXTREME = auto()
    UNKNOWN = auto()


class ResearchQualityState(Enum):
    HEALTHY = auto()
    DEGRADED = auto()
    POOR = auto()
    UNTRUSTED = auto()
    UNAVAILABLE = auto()
    UNKNOWN = auto()


class ResearchRestriction(Enum):
    ALLOW = auto()
    RESTRICT = auto()
    BLOCK = auto()
    NO_ACTION = auto()


@dataclass(frozen=True)
class QualityConfiguration:
    minimum_baseline_samples: int = 5
    maximum_baseline_samples: int = 256
    maximum_age_seconds: int = 300
    elevated_ratio: Decimal = Decimal("1.50")
    high_ratio: Decimal = Decimal("2.00")
    extreme_ratio: Decimal = Decimal("3.00")
    degraded_multiplier: Decimal = Decimal("0.75")
    poor_multiplier: Decimal = Decimal("0.25")
    recovery_confirmations: int = 2
    repeated_failure_limit: int = 3
    maximum_snapshots: int = 512
    maximum_history_per_scope: int = 256
    configuration_snapshot_id: str = "NEUTRAL_QUALITY_DEFAULT"

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.minimum_baseline_samples < 2:
            errors.append("QUALITY_MINIMUM_SAMPLES_INVALID")
        if self.maximum_baseline_samples < self.minimum_baseline_samples:
            errors.append("QUALITY_SAMPLE_BOUND_INVALID")
        if self.maximum_age_seconds < 1 or self.recovery_confirmations < 1:
            errors.append("QUALITY_TEMPORAL_POLICY_INVALID")
        if self.repeated_failure_limit < 1 or min(self.maximum_snapshots, self.maximum_history_per_scope) < 1:
            errors.append("QUALITY_BOUND_INVALID")
        try:
            thresholds = tuple(Decimal(str(x)) for x in (self.elevated_ratio, self.high_ratio, self.extreme_ratio))
            multipliers = tuple(Decimal(str(x)) for x in (self.degraded_multiplier, self.poor_multiplier))
            if any(not x.is_finite() for x in thresholds + multipliers):
                errors.append("QUALITY_NUMERICAL_INVALID")
            if not (ONE <= thresholds[0] < thresholds[1] < thresholds[2]):
                errors.append("QUALITY_THRESHOLD_ORDER_INVALID")
            if not (ZERO <= multipliers[1] <= multipliers[0] <= ONE):
                errors.append("QUALITY_MULTIPLIER_INVALID")
        except (InvalidOperation, ValueError):
            errors.append("QUALITY_NUMERICAL_INVALID")
        return tuple(dict.fromkeys(errors))


@dataclass(frozen=True)
class ScalarObservation:
    observation_id: str
    subject_id: str
    channel_id: str
    value: Decimal
    observed_at_utc: datetime
    available_at_utc: datetime
    source_id: str
    dataset_id: str
    dataset_fingerprint: str
    health: ObservationHealth
    configuration_snapshot_id: str

    @classmethod
    def create(
        cls,
        subject_id: str,
        channel_id: str,
        value: Decimal | str | int,
        observed_at_utc: datetime,
        available_at_utc: datetime,
        source_id: str,
        dataset_id: str,
        dataset_fingerprint: str,
        configuration_snapshot_id: str = "NEUTRAL_QUALITY_DEFAULT",
        health: ObservationHealth = ObservationHealth.HEALTHY,
    ) -> "ScalarObservation":
        normalized = Decimal(str(value))
        identity = deterministic_id(
            "quality_observation",
            subject_id,
            channel_id,
            normalized,
            observed_at_utc.isoformat(),
            available_at_utc.isoformat(),
            source_id,
            dataset_id,
            dataset_fingerprint,
        )
        return cls(identity, subject_id, channel_id, normalized, observed_at_utc, available_at_utc, source_id, dataset_id, dataset_fingerprint, health, configuration_snapshot_id)


@dataclass(frozen=True)
class ObservationBaseline:
    baseline_id: str
    subject_id: str
    channel_id: str
    dataset_id: str
    dataset_fingerprint: str
    median_value: Decimal
    median_absolute_deviation: Decimal
    percentile_90: Decimal
    sample_count: int
    first_observed_at_utc: datetime
    last_observed_at_utc: datetime
    source_observation_ids: tuple[str, ...]
    as_of_timestamp_utc: datetime
    health: ObservationHealth
    configuration_snapshot_id: str


@dataclass(frozen=True)
class DeviationSnapshot:
    deviation_snapshot_id: str
    observation_id: str
    baseline_id: str
    absolute_deviation: Decimal
    relative_ratio: Decimal | None
    percentile_rank: Decimal
    robust_z_score: Decimal | None
    regime: DeviationRegime
    health: ObservationHealth
    reason_codes: tuple[str, ...]
    as_of_timestamp_utc: datetime


@dataclass(frozen=True)
class WorkflowQualityEvidence:
    evidence_id: str
    workflow_snapshot_id: str
    subject_id: str
    failure_count: int
    health: ObservationHealth
    as_of_timestamp_utc: datetime

    @classmethod
    def create(cls, workflow_snapshot_id: str, subject_id: str, failure_count: int, health: ObservationHealth, as_of_timestamp_utc: datetime):
        identity = deterministic_id("workflow_quality_evidence", workflow_snapshot_id, subject_id, failure_count, health.name, as_of_timestamp_utc.isoformat())
        return cls(identity, workflow_snapshot_id, subject_id, failure_count, health, as_of_timestamp_utc)


@dataclass(frozen=True)
class ResearchQualitySnapshot:
    snapshot_id: str
    subject_id: str
    channel_id: str
    observation_id: str | None
    baseline_id: str | None
    deviation_snapshot_id: str | None
    raw_state: ResearchQualityState
    published_state: ResearchQualityState
    restriction: ResearchRestriction
    restriction_multiplier: Decimal
    consecutive_failures: int
    recovery_progress: int
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    as_of_timestamp_utc: datetime
    configuration_snapshot_id: str
    recovery_epoch: int
    engine_version: str
    decision_trace: DecisionTrace


@dataclass(frozen=True)
class QualityRecoveryState:
    schema_version: str
    engine_version: str
    configuration_snapshot_id: str
    recovery_epoch: int
    latest_snapshots: tuple[ResearchQualitySnapshot, ...]
    histories: tuple[tuple[str, tuple[ResearchQualitySnapshot, ...]], ...]


class ObservationQualityEngine:
    def __init__(self, configuration: QualityConfiguration = QualityConfiguration(), audit=None):
        errors = configuration.validate()
        if errors:
            raise ValueError(";".join(errors))
        self.configuration = configuration
        self.audit = audit
        self._lock = RLock()
        self.latest: OrderedDict[str, ResearchQualitySnapshot] = OrderedDict()
        self.histories: dict[str, tuple[ResearchQualitySnapshot, ...]] = defaultdict(tuple)
        self.snapshots: OrderedDict[str, ResearchQualitySnapshot] = OrderedDict()
        self.recovery_restricted = False

    def build_baseline(self, observations: tuple[ScalarObservation, ...], as_of: datetime) -> ObservationBaseline | None:
        admitted = self._admit(observations, as_of)
        if not admitted:
            return None
        scopes = {(item.subject_id, item.channel_id, item.dataset_id, item.dataset_fingerprint, item.configuration_snapshot_id) for item in admitted}
        if len(scopes) != 1 or any(item.health is not ObservationHealth.HEALTHY for item in admitted):
            return None
        admitted = admitted[-self.configuration.maximum_baseline_samples :]
        if len(admitted) < self.configuration.minimum_baseline_samples:
            return None
        values = tuple(item.value for item in admitted)
        midpoint = Decimal(str(median(values)))
        deviations = tuple(abs(value - midpoint) for value in values)
        mad = Decimal(str(median(deviations)))
        p90 = self._percentile(values, Decimal("0.90"))
        ids = tuple(item.observation_id for item in admitted)
        first = min(item.observed_at_utc for item in admitted)
        last = max(item.observed_at_utc for item in admitted)
        subject, channel, dataset_id, fingerprint, configuration_id = next(iter(scopes))
        if configuration_id != self.configuration.configuration_snapshot_id:
            return None
        baseline_id = deterministic_id("quality_baseline", subject, channel, *ids, as_of.isoformat(), configuration_id)
        return ObservationBaseline(baseline_id, subject, channel, dataset_id, fingerprint, midpoint, mad, p90, len(admitted), first, last, ids, as_of, ObservationHealth.HEALTHY, configuration_id)

    def analyze(self, observation: ScalarObservation, baseline: ObservationBaseline, as_of: datetime) -> DeviationSnapshot:
        reasons: list[str] = []
        health = ObservationHealth.HEALTHY
        if not self._valid_observation(observation) or observation.available_at_utc > as_of:
            health = ObservationHealth.INVALID
            reasons.append("QUALITY_OBSERVATION_INVALID_OR_FUTURE")
        if observation.subject_id != baseline.subject_id or observation.channel_id != baseline.channel_id:
            health = ObservationHealth.INVALID
            reasons.append("QUALITY_SCOPE_MISMATCH")
        if observation.dataset_id != baseline.dataset_id or observation.dataset_fingerprint != baseline.dataset_fingerprint:
            health = ObservationHealth.INVALID
            reasons.append("QUALITY_DATASET_LINEAGE_MISMATCH")
        if observation.configuration_snapshot_id != baseline.configuration_snapshot_id:
            health = ObservationHealth.INVALID
            reasons.append("QUALITY_CONFIGURATION_MISMATCH")
        if (as_of - observation.observed_at_utc).total_seconds() > self.configuration.maximum_age_seconds:
            health = ObservationHealth.STALE
            reasons.append("QUALITY_OBSERVATION_STALE")
        absolute = abs(observation.value - baseline.median_value) if observation.value.is_finite() else ZERO
        ratio = observation.value / baseline.median_value if baseline.median_value > ZERO and observation.value.is_finite() else None
        percentile = self._rank(observation.value, baseline, observation) if observation.value.is_finite() else ZERO
        robust_z = absolute / baseline.median_absolute_deviation if baseline.median_absolute_deviation > ZERO else None
        regime = self._regime(ratio) if health is ObservationHealth.HEALTHY else DeviationRegime.UNKNOWN
        if not reasons:
            reasons.append(f"QUALITY_DEVIATION_{regime.name}")
        identity = deterministic_id("quality_deviation", observation.observation_id, baseline.baseline_id, str(absolute), str(ratio), str(percentile), regime.name, as_of.isoformat())
        return DeviationSnapshot(identity, observation.observation_id, baseline.baseline_id, absolute, ratio, percentile, robust_z, regime, health, tuple(reasons), as_of)

    def evaluate(self, observation: ScalarObservation | None, history: tuple[ScalarObservation, ...], as_of: datetime, recovery_epoch: int = 0, workflow_evidence: WorkflowQualityEvidence | None = None) -> ResearchQualitySnapshot:
        with self._lock:
            scope = self._scope(observation)
            reasons: list[str] = []
            warnings: list[str] = []
            baseline = self.build_baseline(history, as_of)
            deviation = None
            if observation is None:
                raw = ResearchQualityState.UNAVAILABLE
                reasons.append("QUALITY_OBSERVATION_UNAVAILABLE")
            elif baseline is None:
                raw = ResearchQualityState.UNAVAILABLE
                reasons.append("QUALITY_BASELINE_UNAVAILABLE")
            else:
                deviation = self.analyze(observation, baseline, as_of)
                if deviation.health is ObservationHealth.INVALID:
                    raw = ResearchQualityState.UNTRUSTED
                elif deviation.health is ObservationHealth.STALE:
                    raw = ResearchQualityState.UNAVAILABLE
                elif deviation.regime is DeviationRegime.NORMAL:
                    raw = ResearchQualityState.HEALTHY
                elif deviation.regime is DeviationRegime.ELEVATED:
                    raw = ResearchQualityState.DEGRADED
                elif deviation.regime is DeviationRegime.HIGH:
                    raw = ResearchQualityState.POOR
                elif deviation.regime is DeviationRegime.EXTREME:
                    raw = ResearchQualityState.UNTRUSTED
                else:
                    raw = ResearchQualityState.UNKNOWN
                reasons.extend(deviation.reason_codes)
            if workflow_evidence is not None:
                if workflow_evidence.as_of_timestamp_utc > as_of or (observation and workflow_evidence.subject_id != observation.subject_id):
                    raw = ResearchQualityState.UNTRUSTED
                    reasons.append("QUALITY_WORKFLOW_EVIDENCE_INVALID")
                elif workflow_evidence.health in (ObservationHealth.INVALID, ObservationHealth.UNAVAILABLE, ObservationHealth.UNKNOWN):
                    raw = ResearchQualityState.UNTRUSTED
                    reasons.append("QUALITY_WORKFLOW_HEALTH_BLOCKED")
                elif workflow_evidence.health in (ObservationHealth.DEGRADED, ObservationHealth.STALE) and raw is ResearchQualityState.HEALTHY:
                    raw = ResearchQualityState.DEGRADED
                    reasons.append("QUALITY_WORKFLOW_HEALTH_DEGRADED")
            previous = self.latest.get(scope)
            published, failures, recovery = self._publish(raw, previous)
            restriction, multiplier = self._restriction(published)
            if failures >= self.configuration.repeated_failure_limit:
                published = ResearchQualityState.UNTRUSTED
                restriction, multiplier = ResearchRestriction.BLOCK, ZERO
                reasons.append("QUALITY_REPEATED_FAILURE_LIMIT")
            snapshot_id = deterministic_id(
                "research_quality_snapshot",
                scope,
                observation.observation_id if observation else "NONE",
                baseline.baseline_id if baseline else "NONE",
                deviation.deviation_snapshot_id if deviation else "NONE",
                workflow_evidence.evidence_id if workflow_evidence else "NONE",
                raw.name,
                published.name,
                failures,
                recovery,
                as_of.isoformat(),
                self.configuration.configuration_snapshot_id,
                recovery_epoch,
            )
            trace = self._trace(snapshot_id, restriction, reasons, as_of, observation, baseline, deviation)
            result = ResearchQualitySnapshot(snapshot_id, observation.subject_id if observation else "UNKNOWN", observation.channel_id if observation else "UNKNOWN", observation.observation_id if observation else None, baseline.baseline_id if baseline else None, deviation.deviation_snapshot_id if deviation else None, raw, published, restriction, multiplier, failures, recovery, tuple(dict.fromkeys(reasons)), tuple(warnings), as_of, self.configuration.configuration_snapshot_id, recovery_epoch, QUALITY_ENGINE_VERSION, trace)
            self.latest[scope] = result
            self.latest.move_to_end(scope)
            self.histories[scope] = (self.histories[scope] + (result,))[-self.configuration.maximum_history_per_scope :]
            self.snapshots[snapshot_id] = result
            self._bound()
            self._record("research_quality_evaluated", {"snapshot_id": snapshot_id, "state": published.name, "restriction": restriction.name})
            return result

    def recovery_state(self, recovery_epoch: int) -> QualityRecoveryState:
        with self._lock:
            return QualityRecoveryState(QUALITY_RECOVERY_SCHEMA_VERSION, QUALITY_ENGINE_VERSION, self.configuration.configuration_snapshot_id, recovery_epoch, tuple(self.latest.values()), tuple(sorted(self.histories.items())))

    def restore(self, state: QualityRecoveryState, expected_recovery_epoch: int) -> bool:
        with self._lock:
            if state.schema_version != QUALITY_RECOVERY_SCHEMA_VERSION or state.engine_version != QUALITY_ENGINE_VERSION or state.configuration_snapshot_id != self.configuration.configuration_snapshot_id or state.recovery_epoch != expected_recovery_epoch:
                self.recovery_restricted = True
                return False
            try:
                snapshots = tuple(state.latest_snapshots)
                if len({item.snapshot_id for item in snapshots}) != len(snapshots):
                    raise ValueError("duplicate snapshot")
                if any(item.configuration_snapshot_id != self.configuration.configuration_snapshot_id or item.recovery_epoch != expected_recovery_epoch or item.restriction_multiplier < ZERO or item.restriction_multiplier > ONE for item in snapshots):
                    raise ValueError("invalid lineage")
                histories = dict(state.histories)
                if any(len(items) > self.configuration.maximum_history_per_scope for items in histories.values()):
                    raise ValueError("history bound")
                latest = OrderedDict()
                for item in snapshots:
                    latest[f"{item.subject_id}|{item.channel_id}"] = item
                self.latest = latest
                self.histories = defaultdict(tuple, histories)
                self.snapshots = OrderedDict((item.snapshot_id, item) for items in histories.values() for item in items)
                self.recovery_restricted = False
                self._bound()
                return True
            except Exception:
                self.recovery_restricted = True
                return False

    def _publish(self, raw: ResearchQualityState, previous: ResearchQualitySnapshot | None) -> tuple[ResearchQualityState, int, int]:
        bad = {ResearchQualityState.POOR, ResearchQualityState.UNTRUSTED, ResearchQualityState.UNAVAILABLE, ResearchQualityState.UNKNOWN}
        if raw in bad:
            failures = (previous.consecutive_failures if previous else 0) + 1
            return raw, failures, 0
        failures = 0
        if previous and previous.published_state in bad:
            progress = previous.recovery_progress + 1
            if progress < self.configuration.recovery_confirmations:
                return previous.published_state, failures, progress
            return raw, failures, 0
        return raw, failures, 0

    def _restriction(self, state: ResearchQualityState) -> tuple[ResearchRestriction, Decimal]:
        if state is ResearchQualityState.HEALTHY:
            return ResearchRestriction.ALLOW, ONE
        if state is ResearchQualityState.DEGRADED:
            return ResearchRestriction.RESTRICT, self.configuration.degraded_multiplier
        if state is ResearchQualityState.POOR:
            return ResearchRestriction.RESTRICT, self.configuration.poor_multiplier
        return ResearchRestriction.BLOCK, ZERO

    def _admit(self, observations: tuple[ScalarObservation, ...], as_of: datetime) -> tuple[ScalarObservation, ...]:
        admitted = [item for item in observations if item.available_at_utc <= as_of and item.observed_at_utc <= as_of and self._valid_observation(item)]
        admitted.sort(key=lambda item: (item.observed_at_utc, item.available_at_utc, item.observation_id))
        return tuple(admitted)

    @staticmethod
    def _valid_observation(item: ScalarObservation) -> bool:
        return bool(item.subject_id and item.channel_id and item.source_id and item.dataset_id and item.dataset_fingerprint and item.value.is_finite() and item.value >= ZERO and item.available_at_utc >= item.observed_at_utc)

    def _regime(self, ratio: Decimal | None) -> DeviationRegime:
        if ratio is None or not ratio.is_finite() or ratio < ZERO:
            return DeviationRegime.UNKNOWN
        if ratio >= self.configuration.extreme_ratio:
            return DeviationRegime.EXTREME
        if ratio >= self.configuration.high_ratio:
            return DeviationRegime.HIGH
        if ratio >= self.configuration.elevated_ratio:
            return DeviationRegime.ELEVATED
        return DeviationRegime.NORMAL

    @staticmethod
    def _percentile(values: tuple[Decimal, ...], percentile: Decimal) -> Decimal:
        ordered = sorted(values)
        if len(ordered) == 1:
            return ordered[0]
        with localcontext() as context:
            context.prec = 28
            position = percentile * Decimal(len(ordered) - 1)
            lower = int(position)
            upper = min(lower + 1, len(ordered) - 1)
            fraction = position - Decimal(lower)
            return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction

    @staticmethod
    def _rank(value: Decimal, baseline: ObservationBaseline, observation: ScalarObservation) -> Decimal:
        if value <= baseline.median_value:
            return Decimal("0.50")
        if baseline.percentile_90 <= baseline.median_value:
            return ONE
        return min(ONE, Decimal("0.50") + Decimal("0.40") * (value - baseline.median_value) / (baseline.percentile_90 - baseline.median_value))

    @staticmethod
    def _scope(observation: ScalarObservation | None) -> str:
        return f"{observation.subject_id}|{observation.channel_id}" if observation else "UNKNOWN|UNKNOWN"

    def _trace(self, snapshot_id, restriction, reasons, as_of, observation, baseline, deviation) -> DecisionTrace:
        passed = restriction in (ResearchRestriction.ALLOW, ResearchRestriction.RESTRICT)
        references = tuple(item for item in (observation.observation_id if observation else None, baseline.baseline_id if baseline else None, deviation.deviation_snapshot_id if deviation else None) if item)
        evaluation = DecisionEvaluation("RESEARCH_QUALITY", DecisionStatus.PASSED if passed else DecisionStatus.FAILED, reasons[-1], "Neutral point-in-time research quality evaluated", references)
        return DecisionTrace(snapshot_id, snapshot_id, as_of, (evaluation,), DecisionOutcome.ACCEPTED if passed else DecisionOutcome.BLOCKED, reasons[-1], as_of, None if passed else "RESEARCH_QUALITY")

    def _bound(self):
        while len(self.snapshots) > self.configuration.maximum_snapshots:
            self.snapshots.popitem(last=False)
        while len(self.latest) > self.configuration.maximum_snapshots:
            self.latest.popitem(last=False)

    def _record(self, event: str, payload: dict):
        if self.audit:
            self.audit.record(event, payload)
