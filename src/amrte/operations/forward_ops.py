"""Forward-only operations for neutral offline workflow research.

No market action, financial account, order, position, wagering, or execution
capability is present in this module.
"""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum, auto
from hashlib import sha256
from pathlib import PurePath, PurePosixPath, PureWindowsPath
from threading import RLock

from amrte.core.identity import deterministic_id
from amrte.core.observability_types import DecisionEvaluation, DecisionOutcome, DecisionStatus, DecisionTrace

VERSION = "1.0"
SCHEMA = "1.0"
ZERO = Decimal("0")


class ValidationStage(Enum):
    HISTORICAL_VALIDATED = auto(); OUT_OF_SAMPLE_VALIDATED = auto(); WALK_FORWARD_VALIDATED = auto()
    FORWARD_SHADOW_VALIDATED = auto(); SOAK_VALIDATED = auto(); WINDOWS_VPS_VALIDATED = auto()
    RESEARCH_OPERATION_APPROVED = auto()


class PromotionDecision(Enum):
    PROMOTE = auto(); HOLD = auto(); DEMOTE = auto(); REVALIDATE = auto(); SUSPEND = auto(); INVALID = auto(); UNKNOWN = auto()


class ChangeClassification(Enum):
    NON_MATERIAL = auto(); REVALIDATION_REQUIRED = auto(); FULL_REVALIDATION_REQUIRED = auto(); UNKNOWN = auto()


class OperationalHealth(Enum):
    HEALTHY = auto(); DEGRADED = auto(); RESTRICTED = auto(); SUSPENDED = auto(); RECOVERY_PENDING = auto(); FAILED = auto(); UNKNOWN = auto()


class SessionStatus(Enum):
    CREATED = auto(); RUNNING = auto(); PAUSED = auto(); COMPLETED = auto(); CANCELLED = auto(); FAILED = auto()


class DriftState(Enum):
    STABLE = auto(); DRIFTED = auto(); INSUFFICIENT = auto(); INVALID = auto()


@dataclass(frozen=True)
class OperationsConfiguration:
    maximum_observations: int = 100000
    maximum_sessions: int = 128
    maximum_events: int = 4096
    maximum_heartbeats: int = 1024
    maximum_log_records: int = 4096
    minimum_forward_observations: int = 10
    maximum_retry_attempts: int = 3
    heartbeat_stale_after: timedelta = timedelta(minutes=5)
    clock_jump_tolerance: timedelta = timedelta(minutes=2)
    low_storage_threshold_bytes: int = 100_000_000
    configuration_snapshot_id: str = "NEUTRAL_FORWARD_OPS_DEFAULT"

    def validate(self):
        ints = (self.maximum_observations, self.maximum_sessions, self.maximum_events,
                self.maximum_heartbeats, self.maximum_log_records,
                self.minimum_forward_observations, self.maximum_retry_attempts,
                self.low_storage_threshold_bytes)
        return ("OPERATIONS_CONFIGURATION_INVALID",) if min(ints) < 1 or self.heartbeat_stale_after <= timedelta(0) or self.clock_jump_tolerance < timedelta(0) else ()


@dataclass(frozen=True)
class ForwardObservation:
    observation_id: str
    source_id: str
    observed_at_utc: datetime
    available_at_utc: datetime
    received_at_utc: datetime
    source_fingerprint: str
    quality_state: str
    sequence_number: int
    neutral_value: Decimal

    @classmethod
    def create(cls, source_id, observed_at_utc, available_at_utc, received_at_utc,
               source_fingerprint, quality_state, sequence_number, neutral_value):
        value = Decimal(str(neutral_value))
        oid = deterministic_id("forward_observation", source_id, observed_at_utc.isoformat(),
                               available_at_utc.isoformat(), received_at_utc.isoformat(),
                               source_fingerprint, sequence_number, value)
        return cls(oid, source_id, observed_at_utc, available_at_utc, received_at_utc,
                   source_fingerprint, quality_state, sequence_number, value)


@dataclass(frozen=True)
class ForwardShadowSession:
    session_id: str
    component_id: str
    component_version: str
    configuration_snapshot_id: str
    historical_cutoff_utc: datetime
    start_utc: datetime
    end_utc: datetime | None
    source_id: str
    environment_id: str
    host_id: str
    validation_policy_id: str
    status: SessionStatus
    observation_ids: tuple[str, ...]
    replay_fingerprint: str | None


@dataclass(frozen=True)
class ForwardShadowDecision:
    decision_id: str
    session_id: str
    observation_id: str
    as_of_utc: datetime
    normalized_result: Decimal
    health: OperationalHealth
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ForwardExpectationDrift:
    drift_id: str
    session_id: str
    dimension: str
    baseline_mean: Decimal
    forward_mean: Decimal
    absolute_delta: Decimal
    threshold: Decimal
    state: DriftState


@dataclass(frozen=True)
class ValidationPromotionRecord:
    record_id: str
    component_id: str
    component_version: str
    configuration_snapshot_id: str
    validation_lineage: str
    source_stage: ValidationStage
    target_stage: ValidationStage
    evidence_ids: tuple[str, ...]
    requested_at_utc: datetime
    approved_at_utc: datetime | None
    decision: PromotionDecision
    reason_codes: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True)
class RuntimeEnvironmentIdentity:
    environment_id: str
    host_id: str
    application_version: str
    configuration_fingerprint: str
    deployment_fingerprint: str
    startup_epoch: int
    process_identity: str
    started_at_utc: datetime


@dataclass(frozen=True)
class WindowsVPSDeploymentProfile:
    profile_id: str
    application_version: str
    runtime_version: str
    dependency_manifest: str
    locations: tuple[tuple[str, str], ...]
    startup_mode: str
    service_identity: str
    health_policy_id: str
    retention_policy_id: str
    recovery_policy_id: str


@dataclass(frozen=True)
class Heartbeat:
    heartbeat_id: str
    environment_id: str
    application_version: str
    timestamp_utc: datetime
    system_health: OperationalHealth
    last_observation_utc: datetime | None
    last_decision_utc: datetime | None
    state_version: int
    recovery_epoch: int


@dataclass(frozen=True)
class BackupManifest:
    backup_id: str
    environment_id: str
    created_at_utc: datetime
    schema_version: str
    application_version: str
    item_fingerprints: tuple[tuple[str, str], ...]
    manifest_checksum: str


@dataclass(frozen=True)
class ResearchSoakQualification:
    soak_id: str
    environment_id: str
    start_utc: datetime
    end_utc: datetime
    observations_processed: int
    decisions_processed: int
    restarts: int
    warnings: int
    errors: int
    peak_memory_bytes: int
    storage_growth_bytes: int
    replay_passed: bool
    recovery_passed: bool
    qualified: bool


@dataclass(frozen=True)
class OperationalReadinessScorecard:
    scorecard_id: str
    dimensions: tuple[tuple[str, OperationalHealth], ...]
    overall_health: OperationalHealth
    decision: PromotionDecision
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class OperationsRecovery:
    schema_version: str
    engine_version: str
    configuration_snapshot_id: str
    recovery_epoch: int
    environment: RuntimeEnvironmentIdentity | None
    sessions: tuple[ForwardShadowSession, ...]
    observations: tuple[ForwardObservation, ...]
    decisions: tuple[ForwardShadowDecision, ...]
    promotions: tuple[ValidationPromotionRecord, ...]
    heartbeats: tuple[Heartbeat, ...]
    paused: bool
    health: OperationalHealth


class NeutralForwardOperationsEngine:
    _STAGES = tuple(ValidationStage)

    def __init__(self, configuration=OperationsConfiguration(), audit=None):
        errors = configuration.validate()
        if errors: raise ValueError(";".join(errors))
        self.configuration = configuration; self.audit = audit; self._lock = RLock()
        self.environment = None; self.sessions = OrderedDict(); self.observations = OrderedDict()
        self.decisions = OrderedDict(); self.promotions = OrderedDict(); self.heartbeats = OrderedDict()
        self.backups = OrderedDict(); self.logs = deque(maxlen=configuration.maximum_log_records)
        self.paused = True; self.health = OperationalHealth.RECOVERY_PENDING
        self.single_instance_token = None; self.last_clock_utc = None; self.recovery_restricted = False

    def startup(self, environment, instance_token, at):
        with self._lock:
            if self.single_instance_token and self.single_instance_token != instance_token:
                return False, ("OPERATIONS_INSTANCE_ALREADY_ACTIVE",)
            if environment.configuration_fingerprint != self.configuration.configuration_snapshot_id or at < environment.started_at_utc:
                self.health = OperationalHealth.FAILED; return False, ("OPERATIONS_STARTUP_INVALID",)
            self.environment = environment; self.single_instance_token = instance_token
            self.last_clock_utc = at; self.health = OperationalHealth.HEALTHY; self.paused = False
            self._record("operations_started", environment.environment_id, at); return True, ("OPERATIONS_STARTED",)

    def shutdown(self, at):
        with self._lock:
            self.paused = True; self.single_instance_token = None
            self._record("operations_stopped", self.environment.environment_id if self.environment else "NONE", at)
            return True

    def create_session(self, component_id, component_version, historical_cutoff_utc,
                       start_utc, source_id, validation_policy_id):
        with self._lock:
            if self.health is not OperationalHealth.HEALTHY or self.paused or not self.environment:
                raise ValueError("OPERATIONS_NOT_READY")
            sid = deterministic_id("forward_session", component_id, component_version,
                                   self.configuration.configuration_snapshot_id,
                                   historical_cutoff_utc.isoformat(), start_utc.isoformat(), source_id,
                                   self.environment.environment_id, validation_policy_id)
            session = ForwardShadowSession(sid, component_id, component_version,
                                           self.configuration.configuration_snapshot_id,
                                           historical_cutoff_utc, start_utc, None, source_id,
                                           self.environment.environment_id, self.environment.host_id,
                                           validation_policy_id, SessionStatus.RUNNING, (), None)
            self.sessions.setdefault(sid, session); return self.sessions[sid]

    def ingest(self, session_id, observation, decision_as_of_utc):
        with self._lock:
            session = self.sessions[session_id]
            if self.paused or self.health not in (OperationalHealth.HEALTHY, OperationalHealth.DEGRADED):
                return None, ("OPERATIONS_RESTRICTED",)
            reasons = []
            if observation.source_id != session.source_id or not observation.neutral_value.is_finite(): reasons.append("OPERATIONS_OBSERVATION_INVALID")
            if observation.observed_at_utc <= session.historical_cutoff_utc: reasons.append("OPERATIONS_NOT_FORWARD_ONLY")
            if observation.observed_at_utc > observation.available_at_utc or observation.available_at_utc > observation.received_at_utc: reasons.append("OPERATIONS_TEMPORAL_INVALID")
            if observation.available_at_utc > decision_as_of_utc: reasons.append("OPERATIONS_LOOKAHEAD_BLOCKED")
            existing_sequence = [x.sequence_number for x in self.observations.values() if x.source_id == observation.source_id]
            if observation.observation_id in self.observations: return self.decisions.get(deterministic_id("forward_decision", session_id, observation.observation_id)), ("OPERATIONS_DUPLICATE",)
            if existing_sequence and observation.sequence_number <= max(existing_sequence): reasons.append("OPERATIONS_SEQUENCE_INVALID")
            if reasons: return None, tuple(sorted(set(reasons)))
            if len(self.observations) >= self.configuration.maximum_observations:
                return None, ("OPERATIONS_OBSERVATION_BOUND",)
            self.observations[observation.observation_id] = observation
            normalized = observation.neutral_value.quantize(Decimal("0.00000001"))
            did = deterministic_id("forward_decision", session_id, observation.observation_id)
            decision = ForwardShadowDecision(did, session_id, observation.observation_id,
                                             decision_as_of_utc, normalized,
                                             OperationalHealth.HEALTHY, ("OPERATIONS_NEUTRAL_RESULT",))
            self.decisions[did] = decision
            self.sessions[session_id] = replace(session, observation_ids=session.observation_ids + (observation.observation_id,))
            return decision, ("OPERATIONS_ACCEPTED",)

    def detect_drift(self, session_id, baseline_mean, threshold):
        values = [self.decisions[deterministic_id("forward_decision", session_id, oid)].normalized_result
                  for oid in self.sessions[session_id].observation_ids]
        baseline = Decimal(str(baseline_mean)); threshold = Decimal(str(threshold))
        if not baseline.is_finite() or not threshold.is_finite() or threshold < ZERO:
            raise ValueError("OPERATIONS_DRIFT_POLICY_INVALID")
        if len(values) < self.configuration.minimum_forward_observations:
            state = DriftState.INSUFFICIENT; forward = ZERO; delta = ZERO
        else:
            forward = sum(values, ZERO) / Decimal(len(values)); delta = abs(forward - baseline)
            state = DriftState.DRIFTED if delta > threshold else DriftState.STABLE
        did = deterministic_id("forward_drift", session_id, baseline, threshold, forward, state.name)
        return ForwardExpectationDrift(did, session_id, "NEUTRAL_VALUE_DISTRIBUTION", baseline,
                                       forward, delta, threshold, state)

    def promote(self, component_id, component_version, validation_lineage, source_stage,
                target_stage, evidence_ids, requested_at, approve=False):
        with self._lock:
            expected = self._STAGES.index(source_stage) + 1
            legal = expected < len(self._STAGES) and self._STAGES[expected] is target_stage
            decision = PromotionDecision.PROMOTE if legal and evidence_ids and approve else PromotionDecision.HOLD
            reasons = ("OPERATIONS_PROMOTION_APPROVED",) if decision is PromotionDecision.PROMOTE else (("OPERATIONS_STAGE_SKIP_BLOCKED",) if not legal else ("OPERATIONS_MANUAL_APPROVAL_REQUIRED",))
            fingerprint = deterministic_id("promotion_fingerprint", component_id, component_version,
                                           self.configuration.configuration_snapshot_id, validation_lineage,
                                           source_stage.name, target_stage.name, *evidence_ids, decision.name)
            rid = deterministic_id("promotion_record", fingerprint)
            record = ValidationPromotionRecord(rid, component_id, component_version,
                                               self.configuration.configuration_snapshot_id,
                                               validation_lineage, source_stage, target_stage,
                                               tuple(evidence_ids), requested_at,
                                               requested_at if decision is PromotionDecision.PROMOTE else None,
                                               decision, reasons, fingerprint)
            self.promotions.setdefault(rid, record); return self.promotions[rid]

    @staticmethod
    def classify_change(changed_fields):
        fields = set(changed_fields)
        if not fields: return ChangeClassification.NON_MATERIAL
        if fields & {"component_logic", "data_transformation", "safety_policy", "lifecycle_semantics"}: return ChangeClassification.FULL_REVALIDATION_REQUIRED
        if fields & {"threshold", "configuration", "dependency_version"}: return ChangeClassification.REVALIDATION_REQUIRED
        return ChangeClassification.UNKNOWN

    def pause(self, reason, at):
        with self._lock:
            self.paused = True; self._record("operations_paused", reason, at); return True

    def resume(self, at):
        with self._lock:
            if self.health is not OperationalHealth.HEALTHY or not self.environment:
                return False, ("OPERATIONS_RESUME_BLOCKED",)
            self.paused = False; self._record("operations_resumed", self.environment.environment_id, at)
            return True, ("OPERATIONS_RESUMED",)

    def heartbeat(self, at, recovery_epoch=0):
        with self._lock:
            self._clock_check(at)
            last_observation = max((x.received_at_utc for x in self.observations.values()), default=None)
            last_decision = max((x.as_of_utc for x in self.decisions.values()), default=None)
            hid = deterministic_id("heartbeat", self.environment.environment_id, at.isoformat(),
                                   self.health.name, len(self.decisions), recovery_epoch)
            heartbeat = Heartbeat(hid, self.environment.environment_id, self.environment.application_version,
                                  at, self.health, last_observation, last_decision, len(self.decisions), recovery_epoch)
            self.heartbeats[hid] = heartbeat
            while len(self.heartbeats) > self.configuration.maximum_heartbeats: self.heartbeats.popitem(last=False)
            return heartbeat

    def storage_check(self, available_bytes):
        if available_bytes < self.configuration.low_storage_threshold_bytes:
            self.health = OperationalHealth.RESTRICTED; self.paused = True; return False
        return True

    def backup(self, items, at):
        if not self.environment: raise ValueError("OPERATIONS_NOT_READY")
        fingerprints = tuple(sorted((name, sha256(data).hexdigest()) for name, data in items.items()))
        checksum = sha256(repr(fingerprints).encode("utf-8")).hexdigest()
        bid = deterministic_id("backup", self.environment.environment_id, at.isoformat(), checksum)
        manifest = BackupManifest(bid, self.environment.environment_id, at, SCHEMA,
                                  self.environment.application_version, fingerprints, checksum)
        self.backups[bid] = manifest; return manifest

    @staticmethod
    def verify_backup(manifest, items):
        fingerprints = tuple(sorted((name, sha256(data).hexdigest()) for name, data in items.items()))
        return fingerprints == manifest.item_fingerprints and sha256(repr(fingerprints).encode("utf-8")).hexdigest() == manifest.manifest_checksum

    @staticmethod
    def deployment_profile(
        application_version,
        runtime_version,
        dependency_manifest,
        locations,
        service_identity="LOCAL_RESEARCH_SERVICE",
    ):
        normalized_items = []

        for name, value in locations.items():
            path = str(value)

            # Deployment locations must be non-empty, relative, and portable
            # regardless of the operating system performing validation.
            if (
                not path
                or path.startswith("~")
                or PurePosixPath(path).is_absolute()
                or PureWindowsPath(path).is_absolute()
                or PureWindowsPath(path).drive
            ):
                raise ValueError("OPERATIONS_PATH_NOT_PORTABLE")

            normalized_items.append((name, str(PurePath(path))))

        normalized = tuple(sorted(normalized_items))

        pid = deterministic_id(
            "windows_profile",
            application_version,
            runtime_version,
            dependency_manifest,
            *[x for pair in normalized for x in pair],
            service_identity,
        )

        return WindowsVPSDeploymentProfile(
            pid,
            application_version,
            runtime_version,
            dependency_manifest,
            normalized,
            "UNATTENDED",
            service_identity,
            "HEALTH_V1",
            "RETENTION_V1",
            "RECOVERY_V1",
        )

    @staticmethod
    def redact(value, secrets):
        result = str(value)
        for secret in secrets:
            if secret: result = result.replace(secret, "[REDACTED]")
        return result

    @staticmethod
    def soak(environment_id, start, end, observations, decisions, restarts,
             warnings, errors, peak_memory, storage_growth, replay, recovery):
        qualified = end > start and observations >= decisions >= 0 and errors == 0 and replay and recovery
        sid = deterministic_id("soak", environment_id, start.isoformat(), end.isoformat(),
                               observations, decisions, restarts, warnings, errors, peak_memory,
                               storage_growth, replay, recovery)
        return ResearchSoakQualification(sid, environment_id, start, end, observations,
                                         decisions, restarts, warnings, errors, peak_memory,
                                         storage_growth, replay, recovery, qualified)

    def readiness(self, dimensions):
        ordered = tuple(sorted(dimensions.items()))
        states = tuple(state for _, state in ordered)
        if OperationalHealth.FAILED in states: overall, decision = OperationalHealth.FAILED, PromotionDecision.SUSPEND
        elif any(x in states for x in (OperationalHealth.RESTRICTED, OperationalHealth.RECOVERY_PENDING, OperationalHealth.UNKNOWN)): overall, decision = OperationalHealth.RESTRICTED, PromotionDecision.HOLD
        elif OperationalHealth.DEGRADED in states: overall, decision = OperationalHealth.DEGRADED, PromotionDecision.HOLD
        else: overall, decision = OperationalHealth.HEALTHY, PromotionDecision.HOLD
        sid = deterministic_id("readiness", *[x for pair in ordered for x in (pair[0], pair[1].name)], overall.name)
        return OperationalReadinessScorecard(sid, ordered, overall, decision, ("OPERATIONS_NO_AUTOMATIC_PROMOTION",))

    def recovery_state(self, epoch):
        return OperationsRecovery(SCHEMA, VERSION, self.configuration.configuration_snapshot_id,
                                  epoch, self.environment, tuple(self.sessions.values()),
                                  tuple(self.observations.values()), tuple(self.decisions.values()),
                                  tuple(self.promotions.values()), tuple(self.heartbeats.values()),
                                  self.paused, self.health)

    def restore(self, state, epoch):
        with self._lock:
            if (state.schema_version, state.engine_version, state.configuration_snapshot_id, state.recovery_epoch) != (SCHEMA, VERSION, self.configuration.configuration_snapshot_id, epoch):
                self.recovery_restricted = True; self.health = OperationalHealth.RECOVERY_PENDING; self.paused = True; return False
            try:
                groups = ((x.session_id for x in state.sessions), (x.observation_id for x in state.observations),
                          (x.decision_id for x in state.decisions), (x.record_id for x in state.promotions),
                          (x.heartbeat_id for x in state.heartbeats))
                if any(len(v := list(g)) != len(set(v)) for g in groups): raise ValueError
                self.environment = state.environment
                self.sessions = OrderedDict((x.session_id, x) for x in state.sessions)
                self.observations = OrderedDict((x.observation_id, x) for x in state.observations)
                self.decisions = OrderedDict((x.decision_id, x) for x in state.decisions)
                self.promotions = OrderedDict((x.record_id, x) for x in state.promotions)
                self.heartbeats = OrderedDict((x.heartbeat_id, x) for x in state.heartbeats)
                if not self.reconcile()[0]: raise ValueError
                self.paused = True; self.health = OperationalHealth.HEALTHY; self.recovery_restricted = False; return True
            except Exception:
                self.recovery_restricted = True; self.health = OperationalHealth.RECOVERY_PENDING; self.paused = True; return False

    def reconcile(self):
        for decision in self.decisions.values():
            if decision.observation_id not in self.observations or decision.session_id not in self.sessions:
                return False, ("OPERATIONS_ORPHAN_DECISION",)
        return True, ()

    def replay_fingerprint(self):
        return deterministic_id("operations_replay", *(x.observation_id for x in self.observations.values()),
                               *(x.decision_id for x in self.decisions.values()),
                               *(x.record_id for x in self.promotions.values()))

    def trace(self, reference_id, at):
        status = DecisionStatus.PASSED if self.health in (OperationalHealth.HEALTHY, OperationalHealth.DEGRADED) else DecisionStatus.FAILED
        evaluation = DecisionEvaluation("NEUTRAL_FORWARD_OPERATIONS", status,
                                        f"OPERATIONS_{self.health.name}",
                                        "Neutral forward-only workflow operation", (reference_id,))
        tid = deterministic_id("operations_trace", reference_id, self.health.name)
        return DecisionTrace(tid, reference_id, at, (evaluation,),
                             DecisionOutcome.ACCEPTED if status is DecisionStatus.PASSED else DecisionOutcome.NO_ACTION,
                             f"OPERATIONS_{self.health.name}", at, None)

    def _clock_check(self, at):
        if self.last_clock_utc and (at < self.last_clock_utc or at - self.last_clock_utc > self.configuration.clock_jump_tolerance):
            self.health = OperationalHealth.RESTRICTED; self.paused = True
        self.last_clock_utc = at

    def _record(self, event, detail, at):
        record = (event, detail, at.isoformat())
        self.logs.append(record)
        if self.audit: self.audit.record(event, {"detail": detail, "at": at.isoformat()})
