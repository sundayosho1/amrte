"""Neutral research-reliability preservation and deterioration governance.

This module operates on abstract quality points. It does not model money,
capital, profit/loss, markets, accounts, positions, or financial execution.
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum, auto
from threading import RLock

from amrte.core.identity import deterministic_id
from amrte.core.observability_types import DecisionEvaluation, DecisionOutcome, DecisionStatus, DecisionTrace


RELIABILITY_ENGINE_VERSION = "1.0"
RELIABILITY_RECOVERY_SCHEMA_VERSION = "1.0"
ZERO = Decimal("0")
ONE = Decimal("1")


class ReliabilityStage(Enum):
    NORMAL = auto()
    WATCH = auto()
    RESTRICTED = auto()
    PROTECTED = auto()
    SUSPENDED = auto()
    UNKNOWN = auto()


class ReliabilityHealth(Enum):
    HEALTHY = auto()
    DEGRADED = auto()
    RESTRICTED = auto()
    INVALID = auto()
    UNKNOWN = auto()


class ReliabilityDecision(Enum):
    ACCEPTED = auto()
    NO_ACTION = auto()
    BLOCKED = auto()
    INVALID = auto()


class ReliabilityReconciliationOutcome(Enum):
    CONSISTENT = auto()
    FAILED_CLOSED = auto()


@dataclass(frozen=True)
class ReliabilityConfiguration:
    starting_index: Decimal = Decimal("100")
    watch_threshold: Decimal = Decimal("0.05")
    restricted_threshold: Decimal = Decimal("0.10")
    protected_threshold: Decimal = Decimal("0.15")
    suspended_threshold: Decimal = Decimal("0.20")
    watch_multiplier: Decimal = Decimal("0.75")
    restricted_multiplier: Decimal = Decimal("0.50")
    protected_multiplier: Decimal = Decimal("0.25")
    recovery_confirmations: int = 2
    maximum_scopes: int = 256
    maximum_events_per_scope: int = 1024
    maximum_snapshots: int = 2048
    maximum_reconciliations: int = 512
    configuration_snapshot_id: str = "NEUTRAL_RELIABILITY_DEFAULT"

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        try:
            numbers = tuple(Decimal(str(x)) for x in (self.starting_index, self.watch_threshold, self.restricted_threshold, self.protected_threshold, self.suspended_threshold, self.watch_multiplier, self.restricted_multiplier, self.protected_multiplier))
            if any(not item.is_finite() for item in numbers) or numbers[0] <= ZERO:
                errors.append("RELIABILITY_NUMERICAL_INVALID")
            if not (ZERO < numbers[1] < numbers[2] < numbers[3] < numbers[4] < ONE):
                errors.append("RELIABILITY_THRESHOLD_ORDER_INVALID")
            if not (ZERO <= numbers[7] <= numbers[6] <= numbers[5] <= ONE):
                errors.append("RELIABILITY_MULTIPLIER_INVALID")
        except (InvalidOperation, ValueError):
            errors.append("RELIABILITY_NUMERICAL_INVALID")
        if self.recovery_confirmations < 1 or min(self.maximum_scopes, self.maximum_events_per_scope, self.maximum_snapshots, self.maximum_reconciliations) < 1:
            errors.append("RELIABILITY_BOUND_INVALID")
        return tuple(dict.fromkeys(errors))


@dataclass(frozen=True)
class QualityOutcomeDelta:
    outcome_id: str
    scope_id: str
    delta_points: Decimal
    observed_at_utc: datetime
    available_at_utc: datetime
    source_lifecycle_id: str
    dataset_fingerprint: str
    configuration_snapshot_id: str
    recovery_epoch: int

    @classmethod
    def create(cls, scope_id, delta_points, observed_at_utc, available_at_utc, source_lifecycle_id, dataset_fingerprint, configuration_snapshot_id="NEUTRAL_RELIABILITY_DEFAULT", recovery_epoch=0):
        delta = Decimal(str(delta_points))
        identity = deterministic_id("quality_outcome_delta", scope_id, delta, observed_at_utc.isoformat(), available_at_utc.isoformat(), source_lifecycle_id, dataset_fingerprint, configuration_snapshot_id, recovery_epoch)
        return cls(identity, scope_id, delta, observed_at_utc, available_at_utc, source_lifecycle_id, dataset_fingerprint, configuration_snapshot_id, recovery_epoch)


@dataclass(frozen=True)
class ResearchReliabilityIndex:
    index_id: str
    scope_id: str
    current_value: Decimal
    best_value: Decimal
    best_observed_at_utc: datetime
    absolute_deterioration: Decimal
    relative_deterioration: Decimal
    raw_stage: ReliabilityStage
    published_stage: ReliabilityStage
    permission_multiplier: Decimal
    recovery_progress: int
    episode_started_at_utc: datetime | None
    underwater_duration_seconds: int
    accepted_outcome_count: int
    last_outcome_id: str | None
    last_observed_at_utc: datetime
    dataset_fingerprint: str
    configuration_snapshot_id: str
    recovery_epoch: int
    health: ReliabilityHealth


@dataclass(frozen=True)
class ReliabilityEvent:
    event_id: str
    scope_id: str
    sequence_number: int
    outcome_id: str
    previous_index_id: str
    new_index_id: str
    previous_stage: ReliabilityStage
    new_stage: ReliabilityStage
    observed_at_utc: datetime
    known_at_utc: datetime
    reason_codes: tuple[str, ...]
    configuration_snapshot_id: str
    recovery_epoch: int


@dataclass(frozen=True)
class ReliabilitySnapshot:
    snapshot_id: str
    scope_id: str
    index_id: str
    current_value: Decimal
    best_value: Decimal
    relative_deterioration: Decimal
    stage: ReliabilityStage
    permission_multiplier: Decimal
    event_ids: tuple[str, ...]
    as_of_timestamp_utc: datetime
    configuration_snapshot_id: str
    recovery_epoch: int


@dataclass(frozen=True)
class ReliabilityProcessingResult:
    decision_id: str
    index: ResearchReliabilityIndex | None
    event: ReliabilityEvent | None
    decision: ReliabilityDecision
    reason_codes: tuple[str, ...]
    decision_trace: DecisionTrace


@dataclass(frozen=True)
class ReliabilityReconciliationResult:
    reconciliation_id: str
    scope_id: str
    expected_value: Decimal
    observed_value: Decimal
    expected_best: Decimal
    observed_best: Decimal
    issues: tuple[str, ...]
    outcome: ReliabilityReconciliationOutcome
    repaired: bool
    as_of_timestamp_utc: datetime


@dataclass(frozen=True)
class ReliabilityRecoveryState:
    schema_version: str
    engine_version: str
    configuration_snapshot_id: str
    recovery_epoch: int
    indices: tuple[ResearchReliabilityIndex, ...]
    versions: tuple[ResearchReliabilityIndex, ...]
    outcomes: tuple[QualityOutcomeDelta, ...]
    events: tuple[ReliabilityEvent, ...]


class ResearchReliabilityEngine:
    def __init__(self, configuration: ReliabilityConfiguration = ReliabilityConfiguration(), audit=None):
        errors = configuration.validate()
        if errors:
            raise ValueError(";".join(errors))
        self.configuration = configuration
        self.audit = audit
        self._lock = RLock()
        self.indices: OrderedDict[str, ResearchReliabilityIndex] = OrderedDict()
        self.versions: OrderedDict[str, ResearchReliabilityIndex] = OrderedDict()
        self.outcomes: OrderedDict[str, QualityOutcomeDelta] = OrderedDict()
        self.events: OrderedDict[str, ReliabilityEvent] = OrderedDict()
        self.events_by_scope: dict[str, tuple[str, ...]] = defaultdict(tuple)
        self.snapshots: OrderedDict[str, ReliabilitySnapshot] = OrderedDict()
        self.reconciliations: OrderedDict[str, ReliabilityReconciliationResult] = OrderedDict()
        self.recovery_restricted = False

    def initialize(self, scope_id: str, dataset_fingerprint: str, as_of: datetime, recovery_epoch: int = 0) -> ResearchReliabilityIndex:
        with self._lock:
            existing = self.indices.get(scope_id)
            if existing:
                return existing
            if not scope_id or not dataset_fingerprint or len(self.indices) >= self.configuration.maximum_scopes:
                raise ValueError("RELIABILITY_INITIALIZATION_INVALID")
            identity = deterministic_id("reliability_index", scope_id, self.configuration.starting_index, dataset_fingerprint, self.configuration.configuration_snapshot_id, recovery_epoch)
            item = ResearchReliabilityIndex(identity, scope_id, self.configuration.starting_index, self.configuration.starting_index, as_of, ZERO, ZERO, ReliabilityStage.NORMAL, ReliabilityStage.NORMAL, ONE, 0, None, 0, 0, None, as_of, dataset_fingerprint, self.configuration.configuration_snapshot_id, recovery_epoch, ReliabilityHealth.HEALTHY)
            self.indices[scope_id] = item
            self.versions[identity] = item
            self._record("reliability_initialized", {"scope_id": scope_id, "index_id": identity})
            return item

    def process(self, outcome: QualityOutcomeDelta, as_of: datetime) -> ReliabilityProcessingResult:
        with self._lock:
            current = self.indices.get(outcome.scope_id)
            if not current:
                return self._result(None, None, ReliabilityDecision.BLOCKED, ("RELIABILITY_SCOPE_UNINITIALIZED",), as_of)
            if outcome.outcome_id in self.outcomes:
                return self._result(current, None, ReliabilityDecision.NO_ACTION, ("RELIABILITY_DUPLICATE_OUTCOME",), as_of)
            reasons: list[str] = []
            if not outcome.delta_points.is_finite():
                reasons.append("RELIABILITY_OUTCOME_NUMERICAL_INVALID")
            if outcome.available_at_utc > as_of or outcome.observed_at_utc > as_of or outcome.available_at_utc < outcome.observed_at_utc or outcome.observed_at_utc < current.last_observed_at_utc:
                reasons.append("RELIABILITY_OUTCOME_TEMPORAL_INVALID")
            if outcome.dataset_fingerprint != current.dataset_fingerprint or outcome.configuration_snapshot_id != current.configuration_snapshot_id or outcome.recovery_epoch != current.recovery_epoch:
                reasons.append("RELIABILITY_OUTCOME_LINEAGE_INVALID")
            if not outcome.source_lifecycle_id:
                reasons.append("RELIABILITY_SOURCE_LIFECYCLE_MISSING")
            if reasons:
                return self._result(current, None, ReliabilityDecision.BLOCKED, tuple(reasons), as_of)
            next_value = max(ZERO, current.current_value + outcome.delta_points)
            best = max(current.best_value, next_value)
            best_at = outcome.observed_at_utc if next_value > current.best_value else current.best_observed_at_utc
            absolute = best - next_value
            relative = absolute / best if best > ZERO else ONE
            raw = self._stage(relative)
            published, recovery = self._publish(raw, current)
            multiplier = self._multiplier(published)
            episode_start = current.episode_started_at_utc
            if relative > ZERO and episode_start is None:
                episode_start = outcome.observed_at_utc
            if relative == ZERO:
                episode_start = None
            duration = int((outcome.observed_at_utc - episode_start).total_seconds()) if episode_start else 0
            index_id = deterministic_id("reliability_index_version", current.index_id, outcome.outcome_id, next_value, best, raw.name, published.name, recovery, as_of.isoformat())
            health = ReliabilityHealth.HEALTHY if published is ReliabilityStage.NORMAL else ReliabilityHealth.DEGRADED if published is ReliabilityStage.WATCH else ReliabilityHealth.RESTRICTED
            updated = ResearchReliabilityIndex(index_id, current.scope_id, next_value, best, best_at, absolute, relative, raw, published, multiplier, recovery, episode_start, duration, current.accepted_outcome_count + 1, outcome.outcome_id, outcome.observed_at_utc, current.dataset_fingerprint, current.configuration_snapshot_id, current.recovery_epoch, health)
            sequence = len(self.events_by_scope[current.scope_id]) + 1
            event_id = deterministic_id("reliability_event", current.scope_id, sequence, outcome.outcome_id, current.index_id, index_id)
            event = ReliabilityEvent(event_id, current.scope_id, sequence, outcome.outcome_id, current.index_id, index_id, current.published_stage, published, outcome.observed_at_utc, as_of, (f"RELIABILITY_STAGE_{published.name}",), current.configuration_snapshot_id, current.recovery_epoch)
            if len(self.events_by_scope[current.scope_id]) >= self.configuration.maximum_events_per_scope:
                return self._result(current, None, ReliabilityDecision.BLOCKED, ("RELIABILITY_HISTORY_BOUND_REACHED",), as_of)
            self.outcomes[outcome.outcome_id] = outcome
            self.indices[current.scope_id] = updated
            self.versions[index_id] = updated
            self.events[event_id] = event
            self.events_by_scope[current.scope_id] += (event_id,)
            self._record("reliability_outcome_accepted", {"scope_id": current.scope_id, "event_id": event_id, "stage": published.name})
            return self._result(updated, event, ReliabilityDecision.ACCEPTED, event.reason_codes, as_of)

    def snapshot(self, scope_id: str, as_of: datetime) -> ReliabilitySnapshot | None:
        with self._lock:
            candidates = [item for item in self.versions.values() if item.scope_id == scope_id and item.last_observed_at_utc <= as_of]
            if not candidates:
                return None
            current = max(candidates, key=lambda item: (item.accepted_outcome_count, item.last_observed_at_utc, item.index_id))
            events = tuple(item.event_id for item in self.events.values() if item.scope_id == scope_id and item.known_at_utc <= as_of and item.sequence_number <= current.accepted_outcome_count)
            identity = deterministic_id("reliability_snapshot", scope_id, current.index_id, *events, as_of.isoformat())
            result = ReliabilitySnapshot(identity, scope_id, current.index_id, current.current_value, current.best_value, current.relative_deterioration, current.published_stage, current.permission_multiplier, events, as_of, current.configuration_snapshot_id, current.recovery_epoch)
            self.snapshots[identity] = result
            while len(self.snapshots) > self.configuration.maximum_snapshots:
                self.snapshots.popitem(last=False)
            return result

    def reconcile(self, scope_id: str, as_of: datetime) -> ReliabilityReconciliationResult:
        with self._lock:
            current = self.indices.get(scope_id)
            events = [self.events[item] for item in self.events_by_scope.get(scope_id, ()) if item in self.events]
            issues: list[str] = []
            if not current:
                expected_value = observed_value = expected_best = observed_best = ZERO
                issues.append("RELIABILITY_SCOPE_MISSING")
            else:
                outcomes = [self.outcomes[event.outcome_id] for event in events if event.outcome_id in self.outcomes]
                expected_value = self.configuration.starting_index
                expected_best = expected_value
                for outcome in outcomes:
                    expected_value = max(ZERO, expected_value + outcome.delta_points)
                    expected_best = max(expected_best, expected_value)
                observed_value, observed_best = current.current_value, current.best_value
                if len(outcomes) != len(events) or [event.sequence_number for event in events] != list(range(1, len(events) + 1)):
                    issues.append("RELIABILITY_SEQUENCE_OR_OUTCOME_MISMATCH")
                if expected_value != observed_value:
                    issues.append("RELIABILITY_INDEX_MISMATCH")
                if expected_best != observed_best:
                    issues.append("RELIABILITY_BEST_MARK_MISMATCH")
                if current.best_value < current.current_value or current.permission_multiplier < ZERO or current.permission_multiplier > ONE:
                    issues.append("RELIABILITY_INVARIANT_INVALID")
            outcome_state = ReliabilityReconciliationOutcome.CONSISTENT if not issues else ReliabilityReconciliationOutcome.FAILED_CLOSED
            identity = deterministic_id("reliability_reconciliation", scope_id, expected_value, observed_value, expected_best, observed_best, *issues, as_of.isoformat())
            result = ReliabilityReconciliationResult(identity, scope_id, expected_value, observed_value, expected_best, observed_best, tuple(issues), outcome_state, False, as_of)
            self.reconciliations[identity] = result
            while len(self.reconciliations) > self.configuration.maximum_reconciliations:
                self.reconciliations.popitem(last=False)
            return result

    def replay_fingerprint(self, scope_id: str) -> str:
        with self._lock:
            current = self.indices.get(scope_id)
            return deterministic_id("reliability_replay", scope_id, current.index_id if current else "MISSING", *self.events_by_scope.get(scope_id, ()))

    def recovery_state(self, recovery_epoch: int) -> ReliabilityRecoveryState:
        with self._lock:
            return ReliabilityRecoveryState(RELIABILITY_RECOVERY_SCHEMA_VERSION, RELIABILITY_ENGINE_VERSION, self.configuration.configuration_snapshot_id, recovery_epoch, tuple(self.indices.values()), tuple(self.versions.values()), tuple(self.outcomes.values()), tuple(self.events.values()))

    def restore(self, state: ReliabilityRecoveryState, expected_recovery_epoch: int) -> bool:
        with self._lock:
            if state.schema_version != RELIABILITY_RECOVERY_SCHEMA_VERSION or state.engine_version != RELIABILITY_ENGINE_VERSION or state.configuration_snapshot_id != self.configuration.configuration_snapshot_id or state.recovery_epoch != expected_recovery_epoch:
                self.recovery_restricted = True
                return False
            try:
                if len(state.indices) > self.configuration.maximum_scopes or len({item.scope_id for item in state.indices}) != len(state.indices) or len({item.index_id for item in state.versions}) != len(state.versions) or len({item.outcome_id for item in state.outcomes}) != len(state.outcomes) or len({item.event_id for item in state.events}) != len(state.events):
                    raise ValueError("duplicate or bounded state")
                indices = OrderedDict((item.scope_id, item) for item in state.indices)
                outcomes = OrderedDict((item.outcome_id, item) for item in state.outcomes)
                groups: dict[str, list[ReliabilityEvent]] = defaultdict(list)
                for event in state.events:
                    if event.scope_id not in indices or event.outcome_id not in outcomes:
                        raise ValueError("orphan event")
                    groups[event.scope_id].append(event)
                for scope_id, current in indices.items():
                    events = sorted(groups[scope_id], key=lambda item: item.sequence_number)
                    if len(events) > self.configuration.maximum_events_per_scope or [item.sequence_number for item in events] != list(range(1, len(events) + 1)) or current.accepted_outcome_count != len(events):
                        raise ValueError("sequence mismatch")
                    value = self.configuration.starting_index
                    best = value
                    for event in events:
                        delta = outcomes[event.outcome_id]
                        if delta.scope_id != scope_id or delta.recovery_epoch != expected_recovery_epoch or delta.configuration_snapshot_id != current.configuration_snapshot_id or delta.dataset_fingerprint != current.dataset_fingerprint:
                            raise ValueError("lineage mismatch")
                        value = max(ZERO, value + delta.delta_points)
                        best = max(best, value)
                    if value != current.current_value or best != current.best_value or current.best_value < current.current_value or not ZERO <= current.permission_multiplier <= ONE:
                        raise ValueError("index mismatch")
                self.indices = indices
                self.versions = OrderedDict((item.index_id, item) for item in state.versions)
                self.outcomes = outcomes
                self.events = OrderedDict((item.event_id, item) for item in state.events)
                self.events_by_scope = defaultdict(tuple, {scope: tuple(event.event_id for event in sorted(events, key=lambda item: item.sequence_number)) for scope, events in groups.items()})
                self.recovery_restricted = False
                return True
            except Exception:
                self.recovery_restricted = True
                return False

    def _stage(self, relative: Decimal) -> ReliabilityStage:
        if relative >= self.configuration.suspended_threshold:
            return ReliabilityStage.SUSPENDED
        if relative >= self.configuration.protected_threshold:
            return ReliabilityStage.PROTECTED
        if relative >= self.configuration.restricted_threshold:
            return ReliabilityStage.RESTRICTED
        if relative >= self.configuration.watch_threshold:
            return ReliabilityStage.WATCH
        return ReliabilityStage.NORMAL

    def _publish(self, raw: ReliabilityStage, current: ResearchReliabilityIndex) -> tuple[ReliabilityStage, int]:
        order = {ReliabilityStage.NORMAL: 0, ReliabilityStage.WATCH: 1, ReliabilityStage.RESTRICTED: 2, ReliabilityStage.PROTECTED: 3, ReliabilityStage.SUSPENDED: 4, ReliabilityStage.UNKNOWN: 5}
        if order[raw] >= order[current.published_stage]:
            return raw, 0
        progress = current.recovery_progress + 1
        if progress < self.configuration.recovery_confirmations:
            return current.published_stage, progress
        recovered_level = max(order[raw], order[current.published_stage] - 1)
        return next(stage for stage, level in order.items() if level == recovered_level), 0

    def _multiplier(self, stage: ReliabilityStage) -> Decimal:
        return {ReliabilityStage.NORMAL: ONE, ReliabilityStage.WATCH: self.configuration.watch_multiplier, ReliabilityStage.RESTRICTED: self.configuration.restricted_multiplier, ReliabilityStage.PROTECTED: self.configuration.protected_multiplier, ReliabilityStage.SUSPENDED: ZERO, ReliabilityStage.UNKNOWN: ZERO}[stage]

    def _result(self, index, event, decision, reasons, as_of):
        correlation = index.scope_id if index else deterministic_id("reliability_missing", *reasons, as_of.isoformat())
        identity = deterministic_id("reliability_decision", correlation, decision.name, *reasons, event.event_id if event else "NONE", as_of.isoformat())
        passed = decision in (ReliabilityDecision.ACCEPTED, ReliabilityDecision.NO_ACTION)
        evaluation = DecisionEvaluation("RESEARCH_RELIABILITY", DecisionStatus.PASSED if passed else DecisionStatus.FAILED, reasons[-1], "Neutral research reliability preservation evaluated", (event.event_id,) if event else ())
        trace = DecisionTrace(identity, correlation, as_of, (evaluation,), DecisionOutcome.ACCEPTED if decision is ReliabilityDecision.ACCEPTED else DecisionOutcome.NO_ACTION if decision is ReliabilityDecision.NO_ACTION else DecisionOutcome.BLOCKED, reasons[-1], as_of, None if passed else "RESEARCH_RELIABILITY")
        return ReliabilityProcessingResult(identity, index, event, decision, tuple(reasons), trace)

    def _record(self, event, payload):
        if self.audit:
            self.audit.record(event, payload)
