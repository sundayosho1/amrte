"""Deterministic governance for neutral research-hypothesis lifecycles.

The lifecycle is an auditable state machine for abstract research artifacts.
It is not a financial position model and has no order or execution capability.
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum, auto
from threading import RLock

from amrte.core.identity import deterministic_id
from amrte.core.observability_types import DecisionEvaluation, DecisionOutcome, DecisionStatus, DecisionTrace


LIFECYCLE_ENGINE_VERSION = "1.0"
LIFECYCLE_RECOVERY_SCHEMA_VERSION = "1.0"


class LifecycleState(Enum):
    PROPOSED = auto()
    VALIDATED = auto()
    AUTHORIZED = auto()
    QUEUED = auto()
    ACTIVATED = auto()
    ACTIVE = auto()
    SAFEGUARDED = auto()
    MONITORED = auto()
    RESOLVED = auto()
    ARCHIVED = auto()
    REJECTED = auto()
    CANCELLED = auto()
    EXPIRED = auto()
    INVALIDATED = auto()
    FAILED = auto()


class TransitionDecision(Enum):
    ALLOW = auto()
    BLOCK = auto()
    NO_ACTION = auto()
    INVALID = auto()


class LifecycleHealth(Enum):
    HEALTHY = auto()
    DEGRADED = auto()
    QUARANTINED = auto()
    INVALID = auto()
    UNKNOWN = auto()


class ReconciliationOutcome(Enum):
    CONSISTENT = auto()
    QUARANTINED = auto()
    RETRY_REQUIRED = auto()
    REVIEW_REQUIRED = auto()
    FAILED_CLOSED = auto()


TERMINAL_STATES = frozenset({LifecycleState.ARCHIVED, LifecycleState.REJECTED, LifecycleState.CANCELLED, LifecycleState.EXPIRED, LifecycleState.INVALIDATED, LifecycleState.FAILED})
ACTIVE_STATES = frozenset({LifecycleState.ACTIVATED, LifecycleState.ACTIVE, LifecycleState.SAFEGUARDED, LifecycleState.MONITORED})

LEGAL_TRANSITIONS = {
    LifecycleState.PROPOSED: frozenset({LifecycleState.VALIDATED, LifecycleState.REJECTED, LifecycleState.CANCELLED, LifecycleState.EXPIRED}),
    LifecycleState.VALIDATED: frozenset({LifecycleState.AUTHORIZED, LifecycleState.REJECTED, LifecycleState.CANCELLED, LifecycleState.EXPIRED}),
    LifecycleState.AUTHORIZED: frozenset({LifecycleState.QUEUED, LifecycleState.CANCELLED, LifecycleState.EXPIRED, LifecycleState.INVALIDATED}),
    LifecycleState.QUEUED: frozenset({LifecycleState.ACTIVATED, LifecycleState.CANCELLED, LifecycleState.EXPIRED, LifecycleState.INVALIDATED, LifecycleState.FAILED}),
    LifecycleState.ACTIVATED: frozenset({LifecycleState.ACTIVE, LifecycleState.SAFEGUARDED, LifecycleState.MONITORED, LifecycleState.RESOLVED, LifecycleState.INVALIDATED, LifecycleState.FAILED}),
    LifecycleState.ACTIVE: frozenset({LifecycleState.SAFEGUARDED, LifecycleState.MONITORED, LifecycleState.RESOLVED, LifecycleState.INVALIDATED, LifecycleState.FAILED}),
    LifecycleState.SAFEGUARDED: frozenset({LifecycleState.MONITORED, LifecycleState.RESOLVED, LifecycleState.INVALIDATED, LifecycleState.FAILED}),
    LifecycleState.MONITORED: frozenset({LifecycleState.SAFEGUARDED, LifecycleState.RESOLVED, LifecycleState.INVALIDATED, LifecycleState.FAILED}),
    LifecycleState.RESOLVED: frozenset({LifecycleState.ARCHIVED}),
}


@dataclass(frozen=True)
class LifecycleConfiguration:
    strict_state_machine: bool = True
    fail_closed: bool = True
    require_lineage: bool = True
    require_dataset_match: bool = True
    require_configuration_match: bool = True
    require_temporal_integrity: bool = True
    require_quality_for_authorization: bool = True
    require_workflow_for_activation: bool = True
    queue_expiration_seconds: int = 3600
    maximum_lifecycles: int = 512
    maximum_transitions_per_lifecycle: int = 128
    maximum_snapshots: int = 2048
    maximum_reconciliations: int = 512
    maximum_cache_entries: int = 512
    configuration_snapshot_id: str = "NEUTRAL_LIFECYCLE_DEFAULT"

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.strict_state_machine or not self.fail_closed:
            errors.append("LIFECYCLE_FAIL_CLOSED_REQUIRED")
        if not all((self.require_lineage, self.require_dataset_match, self.require_configuration_match, self.require_temporal_integrity)):
            errors.append("LIFECYCLE_MANDATORY_VALIDATION_DISABLED")
        if self.queue_expiration_seconds < 1:
            errors.append("LIFECYCLE_EXPIRATION_INVALID")
        if min(self.maximum_lifecycles, self.maximum_transitions_per_lifecycle, self.maximum_snapshots, self.maximum_reconciliations, self.maximum_cache_entries) < 1:
            errors.append("LIFECYCLE_BOUND_INVALID")
        return tuple(dict.fromkeys(errors))


@dataclass(frozen=True)
class LifecyclePreconditionSnapshot:
    snapshot_id: str
    hypothesis_id: str
    lineage_valid: bool
    upstream_authorized: bool
    workflow_healthy: bool
    quality_allowed: bool
    terminal_restriction: bool
    evidence_ids: tuple[str, ...]
    evidence_available_at_utc: datetime
    dataset_fingerprint: str
    configuration_snapshot_id: str
    as_of_timestamp_utc: datetime

    @classmethod
    def create(cls, hypothesis_id, as_of_timestamp_utc, dataset_fingerprint, configuration_snapshot_id="NEUTRAL_LIFECYCLE_DEFAULT", lineage_valid=True, upstream_authorized=True, workflow_healthy=True, quality_allowed=True, terminal_restriction=False, evidence_ids=(), evidence_available_at_utc=None):
        available = evidence_available_at_utc or as_of_timestamp_utc
        identifiers = tuple(sorted(set(evidence_ids)))
        identity = deterministic_id("lifecycle_preconditions", hypothesis_id, lineage_valid, upstream_authorized, workflow_healthy, quality_allowed, terminal_restriction, *identifiers, available.isoformat(), dataset_fingerprint, configuration_snapshot_id, as_of_timestamp_utc.isoformat())
        return cls(identity, hypothesis_id, lineage_valid, upstream_authorized, workflow_healthy, quality_allowed, terminal_restriction, identifiers, available, dataset_fingerprint, configuration_snapshot_id, as_of_timestamp_utc)


@dataclass(frozen=True)
class ResearchHypothesisLifecycle:
    lifecycle_id: str
    hypothesis_id: str
    source_decision_id: str
    family_id: str
    variant_id: str
    subject_id: str
    current_state: LifecycleState
    state_version: int
    last_event_sequence: int
    created_at_utc: datetime
    effective_as_of_utc: datetime
    updated_at_utc: datetime
    dataset_fingerprint: str
    configuration_snapshot_id: str
    last_transition_id: str | None
    health: LifecycleHealth
    engine_version: str
    recovery_epoch: int


@dataclass(frozen=True)
class LifecycleTransition:
    transition_id: str
    lifecycle_id: str
    sequence_number: int
    from_state: LifecycleState
    to_state: LifecycleState
    requested_at_utc: datetime
    effective_at_utc: datetime
    known_at_utc: datetime
    precondition_snapshot_id: str
    evidence_ids: tuple[str, ...]
    trigger_id: str
    reason_codes: tuple[str, ...]
    correlation_id: str
    causation_id: str
    dataset_fingerprint: str
    configuration_snapshot_id: str
    engine_version: str
    recovery_epoch: int


@dataclass(frozen=True)
class LifecycleEvent:
    event_id: str
    transition_id: str
    lifecycle_id: str
    sequence_number: int
    previous_state: LifecycleState
    new_state: LifecycleState
    observed_at_utc: datetime
    known_at_utc: datetime
    effective_at_utc: datetime
    trigger_id: str
    reason_codes: tuple[str, ...]
    dataset_fingerprint: str
    configuration_snapshot_id: str
    recovery_epoch: int


@dataclass(frozen=True)
class LifecycleSnapshot:
    snapshot_id: str
    lifecycle_id: str
    state: LifecycleState
    state_version: int
    last_event_sequence: int
    transition_ids: tuple[str, ...]
    event_ids: tuple[str, ...]
    health: LifecycleHealth
    as_of_timestamp_utc: datetime
    configuration_snapshot_id: str
    recovery_epoch: int


@dataclass(frozen=True)
class LifecycleTransitionResult:
    decision_id: str
    lifecycle: ResearchHypothesisLifecycle | None
    transition: LifecycleTransition | None
    event: LifecycleEvent | None
    decision: TransitionDecision
    reason_codes: tuple[str, ...]
    decision_trace: DecisionTrace


@dataclass(frozen=True)
class LifecycleReconciliationResult:
    reconciliation_id: str
    lifecycle_id: str
    expected_state: LifecycleState | None
    observed_state: LifecycleState | None
    expected_version: int
    observed_version: int
    issues: tuple[str, ...]
    outcome: ReconciliationOutcome
    repaired: bool
    health: LifecycleHealth
    as_of_timestamp_utc: datetime
    recovery_epoch: int


@dataclass(frozen=True)
class LifecycleRecoveryState:
    schema_version: str
    engine_version: str
    configuration_snapshot_id: str
    recovery_epoch: int
    lifecycles: tuple[ResearchHypothesisLifecycle, ...]
    versions: tuple[ResearchHypothesisLifecycle, ...]
    preconditions: tuple[LifecyclePreconditionSnapshot, ...]
    transitions: tuple[LifecycleTransition, ...]
    events: tuple[LifecycleEvent, ...]


class ResearchLifecycleEngine:
    def __init__(self, configuration: LifecycleConfiguration = LifecycleConfiguration(), audit=None):
        errors = configuration.validate()
        if errors:
            raise ValueError(";".join(errors))
        self.configuration = configuration
        self.audit = audit
        self._lock = RLock()
        self.lifecycles: OrderedDict[str, ResearchHypothesisLifecycle] = OrderedDict()
        self.by_hypothesis: dict[str, str] = {}
        self.versions: OrderedDict[str, ResearchHypothesisLifecycle] = OrderedDict()
        self.preconditions: OrderedDict[str, LifecyclePreconditionSnapshot] = OrderedDict()
        self.transitions: OrderedDict[str, LifecycleTransition] = OrderedDict()
        self.events: OrderedDict[str, LifecycleEvent] = OrderedDict()
        self.transitions_by_lifecycle: dict[str, tuple[str, ...]] = defaultdict(tuple)
        self.events_by_lifecycle: dict[str, tuple[str, ...]] = defaultdict(tuple)
        self.snapshots: OrderedDict[str, LifecycleSnapshot] = OrderedDict()
        self.reconciliations: OrderedDict[str, LifecycleReconciliationResult] = OrderedDict()
        self._idempotency: dict[str, str] = {}
        self.recovery_restricted = False

    def create(self, hypothesis_id: str, source_decision_id: str, family_id: str, variant_id: str, subject_id: str, dataset_fingerprint: str, created_at_utc: datetime, recovery_epoch: int = 0) -> LifecycleTransitionResult:
        with self._lock:
            existing_id = self.by_hypothesis.get(hypothesis_id)
            if existing_id:
                return self._result(self.lifecycles[existing_id], None, None, TransitionDecision.NO_ACTION, ("LIFECYCLE_DUPLICATE_CREATION",), created_at_utc)
            if not all((hypothesis_id, source_decision_id, family_id, variant_id, subject_id, dataset_fingerprint)):
                return self._result(None, None, None, TransitionDecision.INVALID, ("LIFECYCLE_LINEAGE_INVALID",), created_at_utc)
            if len(self.lifecycles) >= self.configuration.maximum_lifecycles:
                return self._result(None, None, None, TransitionDecision.BLOCK, ("LIFECYCLE_CAPACITY_REACHED",), created_at_utc)
            lifecycle_id = deterministic_id("research_lifecycle", hypothesis_id, source_decision_id, family_id, variant_id, subject_id, dataset_fingerprint, self.configuration.configuration_snapshot_id, recovery_epoch)
            lifecycle = ResearchHypothesisLifecycle(lifecycle_id, hypothesis_id, source_decision_id, family_id, variant_id, subject_id, LifecycleState.PROPOSED, 0, 0, created_at_utc, created_at_utc, created_at_utc, dataset_fingerprint, self.configuration.configuration_snapshot_id, None, LifecycleHealth.HEALTHY, LIFECYCLE_ENGINE_VERSION, recovery_epoch)
            self.lifecycles[lifecycle_id] = lifecycle
            self.by_hypothesis[hypothesis_id] = lifecycle_id
            self.versions[self._version_key(lifecycle)] = lifecycle
            self._record("lifecycle_created", {"lifecycle_id": lifecycle_id})
            return self._result(lifecycle, None, None, TransitionDecision.ALLOW, ("LIFECYCLE_CREATED",), created_at_utc)

    def transition(self, lifecycle_id: str, to_state: LifecycleState, expected_version: int, preconditions: LifecyclePreconditionSnapshot, as_of: datetime, trigger_id: str, correlation_id: str = "LIFECYCLE", causation_id: str = "LIFECYCLE") -> LifecycleTransitionResult:
        with self._lock:
            lifecycle = self.lifecycles.get(lifecycle_id)
            if not lifecycle:
                return self._result(None, None, None, TransitionDecision.INVALID, ("LIFECYCLE_MISSING",), as_of)
            if lifecycle.current_state is to_state:
                return self._result(lifecycle, None, None, TransitionDecision.NO_ACTION, ("LIFECYCLE_ALREADY_IN_STATE",), as_of)
            if lifecycle.current_state in TERMINAL_STATES:
                return self._result(lifecycle, None, None, TransitionDecision.BLOCK, ("LIFECYCLE_TERMINAL_IMMUTABLE",), as_of)
            if expected_version != lifecycle.state_version:
                return self._result(lifecycle, None, None, TransitionDecision.BLOCK, ("LIFECYCLE_VERSION_CONFLICT",), as_of)
            if to_state not in LEGAL_TRANSITIONS.get(lifecycle.current_state, frozenset()):
                return self._result(lifecycle, None, None, TransitionDecision.BLOCK, ("LIFECYCLE_TRANSITION_ILLEGAL",), as_of)
            if len(self.transitions_by_lifecycle[lifecycle_id]) >= self.configuration.maximum_transitions_per_lifecycle:
                return self._result(lifecycle, None, None, TransitionDecision.BLOCK, ("LIFECYCLE_HISTORY_BOUND_REACHED",), as_of)
            reasons = self._validate_preconditions(lifecycle, to_state, preconditions, as_of)
            if reasons:
                return self._result(lifecycle, None, None, TransitionDecision.BLOCK, reasons, as_of)
            idempotency_key = deterministic_id("lifecycle_transition_request", lifecycle_id, expected_version, lifecycle.current_state.name, to_state.name, trigger_id, as_of.isoformat(), self.configuration.configuration_snapshot_id)
            if idempotency_key in self._idempotency:
                return self._result(lifecycle, None, None, TransitionDecision.NO_ACTION, ("LIFECYCLE_DUPLICATE_TRANSITION",), as_of)
            sequence = lifecycle.last_event_sequence + 1
            transition_id = deterministic_id("lifecycle_transition", idempotency_key, preconditions.snapshot_id, sequence, lifecycle.recovery_epoch)
            transition = LifecycleTransition(transition_id, lifecycle_id, sequence, lifecycle.current_state, to_state, as_of, as_of, as_of, preconditions.snapshot_id, preconditions.evidence_ids, trigger_id, (f"LIFECYCLE_{to_state.name}",), correlation_id, causation_id, lifecycle.dataset_fingerprint, lifecycle.configuration_snapshot_id, LIFECYCLE_ENGINE_VERSION, lifecycle.recovery_epoch)
            event_id = deterministic_id("lifecycle_event", transition_id, sequence, lifecycle.current_state.name, to_state.name)
            event = LifecycleEvent(event_id, transition_id, lifecycle_id, sequence, lifecycle.current_state, to_state, as_of, as_of, as_of, trigger_id, transition.reason_codes, lifecycle.dataset_fingerprint, lifecycle.configuration_snapshot_id, lifecycle.recovery_epoch)
            updated = replace(lifecycle, current_state=to_state, state_version=lifecycle.state_version + 1, last_event_sequence=sequence, updated_at_utc=as_of, effective_as_of_utc=as_of, last_transition_id=transition_id)
            self.preconditions[preconditions.snapshot_id] = preconditions
            self.transitions[transition_id] = transition
            self.events[event_id] = event
            self.transitions_by_lifecycle[lifecycle_id] += (transition_id,)
            self.events_by_lifecycle[lifecycle_id] += (event_id,)
            self.lifecycles[lifecycle_id] = updated
            self.versions[self._version_key(updated)] = updated
            self._idempotency[idempotency_key] = transition_id
            self._record("lifecycle_transition_committed", {"lifecycle_id": lifecycle_id, "transition_id": transition_id, "state": to_state.name})
            return self._result(updated, transition, event, TransitionDecision.ALLOW, transition.reason_codes, as_of)

    def snapshot(self, lifecycle_id: str, as_of: datetime) -> LifecycleSnapshot | None:
        with self._lock:
            candidates = [item for item in self.versions.values() if item.lifecycle_id == lifecycle_id and item.updated_at_utc <= as_of]
            if not candidates:
                return None
            current = max(candidates, key=lambda item: (item.state_version, item.updated_at_utc))
            transitions = tuple(item.transition_id for item in self.transitions.values() if item.lifecycle_id == lifecycle_id and item.known_at_utc <= as_of and item.sequence_number <= current.last_event_sequence)
            events = tuple(item.event_id for item in self.events.values() if item.lifecycle_id == lifecycle_id and item.known_at_utc <= as_of and item.sequence_number <= current.last_event_sequence)
            snapshot_id = deterministic_id("lifecycle_snapshot", lifecycle_id, current.state_version, *transitions, *events, as_of.isoformat(), current.configuration_snapshot_id, current.recovery_epoch)
            result = LifecycleSnapshot(snapshot_id, lifecycle_id, current.current_state, current.state_version, current.last_event_sequence, transitions, events, current.health, as_of, current.configuration_snapshot_id, current.recovery_epoch)
            self.snapshots[snapshot_id] = result
            while len(self.snapshots) > self.configuration.maximum_snapshots:
                self.snapshots.popitem(last=False)
            return result

    def expire_if_due(self, lifecycle_id: str, as_of: datetime, trigger_id: str = "QUEUE_EXPIRY") -> LifecycleTransitionResult:
        """Expire only a queued lifecycle whose configured neutral queue age elapsed."""
        with self._lock:
            lifecycle = self.lifecycles.get(lifecycle_id)
            if not lifecycle:
                return self._result(None, None, None, TransitionDecision.INVALID, ("LIFECYCLE_MISSING",), as_of)
            if lifecycle.current_state is not LifecycleState.QUEUED:
                return self._result(lifecycle, None, None, TransitionDecision.NO_ACTION, ("LIFECYCLE_QUEUE_EXPIRY_NOT_APPLICABLE",), as_of)
            if as_of < lifecycle.updated_at_utc + timedelta(seconds=self.configuration.queue_expiration_seconds):
                return self._result(lifecycle, None, None, TransitionDecision.NO_ACTION, ("LIFECYCLE_QUEUE_NOT_EXPIRED",), as_of)
            preconditions = LifecyclePreconditionSnapshot.create(lifecycle.hypothesis_id, as_of, lifecycle.dataset_fingerprint, lifecycle.configuration_snapshot_id, evidence_ids=(trigger_id,))
            return self.transition(lifecycle_id, LifecycleState.EXPIRED, lifecycle.state_version, preconditions, as_of, trigger_id)

    def replay_fingerprint(self, lifecycle_id: str) -> str:
        """Return a deterministic fingerprint of the committed immutable history."""
        with self._lock:
            lifecycle = self.lifecycles.get(lifecycle_id)
            if not lifecycle:
                return deterministic_id("lifecycle_replay", lifecycle_id, "MISSING")
            transition_ids = self.transitions_by_lifecycle.get(lifecycle_id, ())
            event_ids = self.events_by_lifecycle.get(lifecycle_id, ())
            return deterministic_id("lifecycle_replay", lifecycle_id, lifecycle.state_version, lifecycle.current_state.name, *transition_ids, *event_ids, lifecycle.dataset_fingerprint, lifecycle.configuration_snapshot_id, lifecycle.recovery_epoch)

    def reconcile(self, lifecycle_id: str, as_of: datetime) -> LifecycleReconciliationResult:
        with self._lock:
            lifecycle = self.lifecycles.get(lifecycle_id)
            issues: list[str] = []
            transition_ids = self.transitions_by_lifecycle.get(lifecycle_id, ())
            event_ids = self.events_by_lifecycle.get(lifecycle_id, ())
            transitions = [self.transitions[item] for item in transition_ids if item in self.transitions]
            events = [self.events[item] for item in event_ids if item in self.events]
            if not lifecycle:
                issues.append("LIFECYCLE_MISSING")
                expected_state = observed_state = None
                expected_version = observed_version = 0
            else:
                expected_state = transitions[-1].to_state if transitions else LifecycleState.PROPOSED
                observed_state = lifecycle.current_state
                expected_version = len(transitions)
                observed_version = lifecycle.state_version
                sequences = [item.sequence_number for item in transitions]
                if sequences != list(range(1, len(sequences) + 1)):
                    issues.append("LIFECYCLE_SEQUENCE_GAP_OR_COLLISION")
                if len(events) != len(transitions) or [item.sequence_number for item in events] != sequences:
                    issues.append("LIFECYCLE_EVENT_TRANSITION_MISMATCH")
                if expected_state is not observed_state:
                    issues.append("LIFECYCLE_STATE_MISMATCH")
                if expected_version != observed_version or lifecycle.last_event_sequence != len(events):
                    issues.append("LIFECYCLE_VERSION_MISMATCH")
                if lifecycle.hypothesis_id not in self.by_hypothesis or self.by_hypothesis.get(lifecycle.hypothesis_id) != lifecycle_id:
                    issues.append("LIFECYCLE_ORPHAN_OR_DUPLICATE")
                if any(item.dataset_fingerprint != lifecycle.dataset_fingerprint or item.configuration_snapshot_id != lifecycle.configuration_snapshot_id or item.recovery_epoch != lifecycle.recovery_epoch for item in transitions + events):
                    issues.append("LIFECYCLE_LINEAGE_MISMATCH")
                if any(event.transition_id != transition.transition_id for event, transition in zip(events, transitions)):
                    issues.append("LIFECYCLE_ORPHAN_EVENT")
            outcome = ReconciliationOutcome.CONSISTENT if not issues else ReconciliationOutcome.FAILED_CLOSED
            health = LifecycleHealth.HEALTHY if not issues else LifecycleHealth.QUARANTINED
            identity = deterministic_id("lifecycle_reconciliation", lifecycle_id, expected_state, observed_state, expected_version, observed_version, *issues, as_of.isoformat())
            result = LifecycleReconciliationResult(identity, lifecycle_id, expected_state, observed_state, expected_version, observed_version, tuple(issues), outcome, False, health, as_of, lifecycle.recovery_epoch if lifecycle else 0)
            self.reconciliations[identity] = result
            while len(self.reconciliations) > self.configuration.maximum_reconciliations:
                self.reconciliations.popitem(last=False)
            return result

    def recovery_state(self, recovery_epoch: int) -> LifecycleRecoveryState:
        with self._lock:
            return LifecycleRecoveryState(LIFECYCLE_RECOVERY_SCHEMA_VERSION, LIFECYCLE_ENGINE_VERSION, self.configuration.configuration_snapshot_id, recovery_epoch, tuple(self.lifecycles.values()), tuple(self.versions.values()), tuple(self.preconditions.values()), tuple(self.transitions.values()), tuple(self.events.values()))

    def restore(self, state: LifecycleRecoveryState, expected_recovery_epoch: int) -> bool:
        with self._lock:
            if state.schema_version != LIFECYCLE_RECOVERY_SCHEMA_VERSION or state.engine_version != LIFECYCLE_ENGINE_VERSION or state.configuration_snapshot_id != self.configuration.configuration_snapshot_id or state.recovery_epoch != expected_recovery_epoch:
                self.recovery_restricted = True
                return False
            try:
                if len(state.lifecycles) > self.configuration.maximum_lifecycles:
                    raise ValueError("lifecycle bound")
                if len({item.lifecycle_id for item in state.lifecycles}) != len(state.lifecycles) or len({item.hypothesis_id for item in state.lifecycles}) != len(state.lifecycles):
                    raise ValueError("duplicate lifecycle")
                if len({item.transition_id for item in state.transitions}) != len(state.transitions) or len({item.event_id for item in state.events}) != len(state.events):
                    raise ValueError("duplicate records")
                lifecycles = OrderedDict((item.lifecycle_id, item) for item in state.lifecycles)
                transition_groups: dict[str, list[LifecycleTransition]] = defaultdict(list)
                event_groups: dict[str, list[LifecycleEvent]] = defaultdict(list)
                for item in state.transitions:
                    if item.lifecycle_id not in lifecycles or item.known_at_utc < lifecycles[item.lifecycle_id].created_at_utc:
                        raise ValueError("orphan or temporal transition")
                    transition_groups[item.lifecycle_id].append(item)
                for item in state.events:
                    if item.lifecycle_id not in lifecycles:
                        raise ValueError("orphan event")
                    event_groups[item.lifecycle_id].append(item)
                for lifecycle_id, lifecycle in lifecycles.items():
                    transitions = sorted(transition_groups[lifecycle_id], key=lambda item: item.sequence_number)
                    events = sorted(event_groups[lifecycle_id], key=lambda item: item.sequence_number)
                    if len(transitions) > self.configuration.maximum_transitions_per_lifecycle or [item.sequence_number for item in transitions] != list(range(1, len(transitions) + 1)) or [item.sequence_number for item in events] != list(range(1, len(events) + 1)) or len(transitions) != len(events):
                        raise ValueError("sequence mismatch")
                    expected = transitions[-1].to_state if transitions else LifecycleState.PROPOSED
                    if lifecycle.current_state is not expected or lifecycle.state_version != len(transitions) or lifecycle.last_event_sequence != len(events):
                        raise ValueError("state mismatch")
                    if any(t.to_state not in LEGAL_TRANSITIONS.get(t.from_state, frozenset()) or t.dataset_fingerprint != lifecycle.dataset_fingerprint or t.configuration_snapshot_id != lifecycle.configuration_snapshot_id or t.recovery_epoch != expected_recovery_epoch for t in transitions):
                        raise ValueError("invalid transition lineage")
                    if any(e.transition_id != t.transition_id for e, t in zip(events, transitions)):
                        raise ValueError("event mismatch")
                self.lifecycles = lifecycles
                self.by_hypothesis = {item.hypothesis_id: item.lifecycle_id for item in state.lifecycles}
                self.versions = OrderedDict((self._version_key(item), item) for item in state.versions)
                self.preconditions = OrderedDict((item.snapshot_id, item) for item in state.preconditions)
                self.transitions = OrderedDict((item.transition_id, item) for item in state.transitions)
                self.events = OrderedDict((item.event_id, item) for item in state.events)
                self.transitions_by_lifecycle = defaultdict(tuple, {key: tuple(item.transition_id for item in sorted(values, key=lambda x: x.sequence_number)) for key, values in transition_groups.items()})
                self.events_by_lifecycle = defaultdict(tuple, {key: tuple(item.event_id for item in sorted(values, key=lambda x: x.sequence_number)) for key, values in event_groups.items()})
                self._idempotency = {}
                self.recovery_restricted = False
                return True
            except Exception:
                self.recovery_restricted = True
                return False

    def _validate_preconditions(self, lifecycle, to_state, preconditions, as_of) -> tuple[str, ...]:
        reasons: list[str] = []
        if preconditions.hypothesis_id != lifecycle.hypothesis_id or not preconditions.lineage_valid:
            reasons.append("LIFECYCLE_PRECONDITION_LINEAGE_INVALID")
        if preconditions.dataset_fingerprint != lifecycle.dataset_fingerprint:
            reasons.append("LIFECYCLE_DATASET_MISMATCH")
        if preconditions.configuration_snapshot_id != lifecycle.configuration_snapshot_id:
            reasons.append("LIFECYCLE_CONFIGURATION_MISMATCH")
        if preconditions.as_of_timestamp_utc != as_of or preconditions.evidence_available_at_utc > as_of or as_of < lifecycle.updated_at_utc:
            reasons.append("LIFECYCLE_TEMPORAL_INVALID")
        if preconditions.terminal_restriction and to_state not in {LifecycleState.REJECTED, LifecycleState.CANCELLED, LifecycleState.EXPIRED, LifecycleState.INVALIDATED, LifecycleState.FAILED, LifecycleState.RESOLVED}:
            reasons.append("LIFECYCLE_TERMINAL_RESTRICTION")
        if to_state is LifecycleState.AUTHORIZED and (not preconditions.upstream_authorized or (self.configuration.require_quality_for_authorization and not preconditions.quality_allowed)):
            reasons.append("LIFECYCLE_AUTHORIZATION_PRECONDITION_FAILED")
        if to_state is LifecycleState.ACTIVATED and self.configuration.require_workflow_for_activation and not preconditions.workflow_healthy:
            reasons.append("LIFECYCLE_WORKFLOW_PRECONDITION_FAILED")
        return tuple(dict.fromkeys(reasons))

    def _result(self, lifecycle, transition, event, decision, reasons, as_of):
        reference = lifecycle.lifecycle_id if lifecycle else deterministic_id("lifecycle_missing", *reasons, as_of.isoformat())
        decision_id = deterministic_id("lifecycle_decision", reference, decision.name, *reasons, transition.transition_id if transition else "NONE", as_of.isoformat())
        passed = decision in (TransitionDecision.ALLOW, TransitionDecision.NO_ACTION)
        evaluation = DecisionEvaluation("RESEARCH_LIFECYCLE", DecisionStatus.PASSED if passed else DecisionStatus.FAILED, reasons[-1], "Neutral research lifecycle transition evaluated", tuple(item for item in (transition.transition_id if transition else None, event.event_id if event else None) if item))
        outcome = DecisionOutcome.ACCEPTED if decision is TransitionDecision.ALLOW else DecisionOutcome.NO_ACTION if decision is TransitionDecision.NO_ACTION else DecisionOutcome.BLOCKED
        trace = DecisionTrace(decision_id, reference, as_of, (evaluation,), outcome, reasons[-1], as_of, None if passed else "RESEARCH_LIFECYCLE")
        return LifecycleTransitionResult(decision_id, lifecycle, transition, event, decision, tuple(reasons), trace)

    @staticmethod
    def _version_key(lifecycle):
        return f"{lifecycle.lifecycle_id}:{lifecycle.state_version}"

    def _record(self, event, payload):
        if self.audit:
            self.audit.record(event, payload)
