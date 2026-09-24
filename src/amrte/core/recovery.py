from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping

from .constants import AMRTE_VERSION, STATE_SCHEMA_VERSION
from .errors import AMRTEError, Result
from .interfaces import IAuditSink, IClock
from .persistence import LocalCheckpointRepository, classify_state_schema
from .persistence_types import (
    Checkpoint, EventCommitStatus, ObjectRecoveryStatus, RecoveryConfidence,
    RecoveryMode, RecoveryOutcome, RecoveryReport, ReconciliationStatus,
    ReplayDescriptor, ShutdownStatus, StateCompatibility, StorageHealth,
)
from .types import EffectiveConfigurationSnapshot, Severity


PROTECTED_STATES = frozenset({"DEFENSIVE", "PROTECT", "SUSPENDED", "ERROR"})


@dataclass(frozen=True)
class RecoveryContext:
    configuration: EffectiveConfigurationSnapshot
    dataset_id: str
    dataset_fingerprint: str
    expected_experiment_id: str | None = None
    recovery_expected: bool = False
    maximum_checkpoint_age_seconds: int | None = None


class IdempotencyLedger:
    def __init__(self, committed: Iterable[str] = ()):
        values = tuple(committed)
        if len(set(values)) != len(values):
            raise ValueError("duplicate idempotency keys in recovered state")
        self._committed = set(values)

    def is_committed(self, key: str) -> bool:
        return key in self._committed

    def commit(self, key: str) -> bool:
        if not key or key in self._committed:
            return False
        self._committed.add(key)
        return True

    def snapshot(self) -> tuple[str, ...]:
        return tuple(sorted(self._committed))


def reconcile_owned_objects(payload: Mapping[str, Any]) -> tuple[ObjectRecoveryStatus | None, tuple[str, ...]]:
    objects = payload.get("objects", [])
    known_owners = set(payload.get("known_owner_ids", []))
    orphan_ids = tuple(sorted(str(item.get("id", "UNKNOWN")) for item in objects
                              if item.get("owner_id") not in known_owners))
    if orphan_ids:
        return ObjectRecoveryStatus.MANUAL_REVIEW, orphan_ids
    return None, ()


def reconcile_ghosts(payload: Mapping[str, Any]) -> tuple[ObjectRecoveryStatus | None, tuple[str, ...]]:
    persisted = set(map(str, payload.get("expected_object_ids", [])))
    reconstructed = set(map(str, payload.get("actual_object_ids", [])))
    ghosts = tuple(sorted(persisted - reconstructed))
    if ghosts:
        return ObjectRecoveryStatus.MANUAL_REVIEW, ghosts
    return None, ()


def replay_descriptor(checkpoint: Checkpoint) -> ReplayDescriptor:
    payload = checkpoint.state_payload
    return ReplayDescriptor(
        application_version=checkpoint.application_version,
        configuration_hash=checkpoint.configuration_hash,
        dataset_fingerprint=checkpoint.dataset_fingerprint,
        starting_checkpoint_id=checkpoint.checkpoint_id,
        seed=int(payload.get("random_seed", 0)),
        random_sequence_position=int(payload.get("random_sequence_position", 0)),
        event_sequence=int(payload.get("last_committed_sequence", 0)),
    )


class RecoveryEngine:
    def __init__(self, repository: LocalCheckpointRepository, clock: IClock,
                 audit: IAuditSink):
        self.repository = repository
        self.clock = clock
        self.audit = audit

    def recover(self, context: RecoveryContext,
                mode: RecoveryMode = RecoveryMode.AUTO_SAFE) -> RecoveryReport:
        self.audit.record("recovery_started", {"mode": mode.name})
        if mode is RecoveryMode.RECOVERY_DISABLED:
            return self._report(RecoveryOutcome.RECOVERY_FAILED, RecoveryConfidence.UNSAFE,
                                reasons=("recovery is disabled",))
        if mode is RecoveryMode.MANUAL_REVIEW_REQUIRED:
            return self._report(RecoveryOutcome.RECOVERY_REQUIRES_MANUAL_REVIEW,
                                RecoveryConfidence.AMBIGUOUS,
                                reasons=("manual review was explicitly requested",))
        if mode is RecoveryMode.START_NEW_RUN:
            return self._report(RecoveryOutcome.RECOVERY_NEW_RUN,
                                RecoveryConfidence.DETERMINISTIC, ready=True)
        initialized = self.repository.initialize()
        if not initialized.success:
            return self._report(RecoveryOutcome.RECOVERY_FAILED,
                                RecoveryConfidence.UNSAFE,
                                reasons=(initialized.error.message if initialized.error else "storage unavailable",))
        discovered = self.repository.enumerate_checkpoints()
        self.audit.record("checkpoints_discovered", {"count": len(discovered)})
        if not discovered:
            if context.recovery_expected:
                return self._report(RecoveryOutcome.RECOVERY_REQUIRES_MANUAL_REVIEW,
                                    RecoveryConfidence.AMBIGUOUS,
                                    reasons=("expected recovery checkpoint is missing",))
            return self._report(RecoveryOutcome.RECOVERY_NEW_RUN,
                                RecoveryConfidence.DETERMINISTIC, ready=True)
        loaded = self.repository.latest_valid(quarantine_invalid=True)
        if not loaded.success:
            return self._report(RecoveryOutcome.RECOVERY_CORRUPTED,
                                RecoveryConfidence.UNSAFE,
                                reasons=(loaded.error.message if loaded.error else "state corrupted",))
        checkpoint = loaded.value
        self.audit.record("checkpoint_selected", {
            "checkpoint_id": checkpoint.checkpoint_id,
            "fallback": self.repository.last_load_used_fallback,
        })
        reasons: list[str] = []
        warnings: list[str] = []
        compatibility = classify_state_schema(checkpoint.state_schema_version)
        if compatibility not in (StateCompatibility.CURRENT, StateCompatibility.COMPATIBLE):
            return self._report(RecoveryOutcome.RECOVERY_INCOMPATIBLE,
                                RecoveryConfidence.UNSAFE, checkpoint,
                                reasons=(f"state schema is {compatibility.name}",))
        chain = self.repository.validate_chain()
        if not chain.success and not self.repository.last_load_used_fallback:
            return self._report(RecoveryOutcome.RECOVERY_REQUIRES_MANUAL_REVIEW,
                                RecoveryConfidence.AMBIGUOUS, checkpoint,
                                reasons=(chain.error.message,))
        config_status = (ReconciliationStatus.MATCH if
                         checkpoint.configuration_hash == context.configuration.configuration_hash
                         else ReconciliationStatus.INCOMPATIBLE_CHANGE)
        if config_status is not ReconciliationStatus.MATCH:
            return self._report(RecoveryOutcome.RECOVERY_REQUIRES_MANUAL_REVIEW,
                                RecoveryConfidence.AMBIGUOUS, checkpoint,
                                reasons=("configuration fingerprint mismatch",),
                                config=config_status)
        dataset_status = (ReconciliationStatus.MATCH if
                          checkpoint.dataset_id == context.dataset_id and
                          checkpoint.dataset_fingerprint == context.dataset_fingerprint
                          else ReconciliationStatus.INCOMPATIBLE_CHANGE)
        if dataset_status is not ReconciliationStatus.MATCH:
            return self._report(RecoveryOutcome.RECOVERY_REQUIRES_MANUAL_REVIEW,
                                RecoveryConfidence.AMBIGUOUS, checkpoint,
                                reasons=("dataset identity or fingerprint mismatch",),
                                config=config_status, dataset=dataset_status)
        if context.expected_experiment_id and checkpoint.experiment_id != context.expected_experiment_id:
            return self._report(RecoveryOutcome.RECOVERY_REQUIRES_MANUAL_REVIEW,
                                RecoveryConfidence.AMBIGUOUS, checkpoint,
                                reasons=("experiment identity mismatch",),
                                config=config_status, dataset=dataset_status)
        if context.maximum_checkpoint_age_seconds is not None:
            age = (self.clock.now() - checkpoint.created_at).total_seconds()
            if age > context.maximum_checkpoint_age_seconds:
                return self._report(RecoveryOutcome.RECOVERY_REQUIRES_MANUAL_REVIEW,
                                    RecoveryConfidence.AMBIGUOUS, checkpoint,
                                    reasons=("checkpoint is stale",), config=config_status,
                                    dataset=dataset_status)
        payload = checkpoint.state_payload
        event_status_name = str(payload.get("event_status", EventCommitStatus.NOT_STARTED.name))
        try:
            event_status = EventCommitStatus[event_status_name]
        except KeyError:
            return self._report(RecoveryOutcome.RECOVERY_CORRUPTED,
                                RecoveryConfidence.UNSAFE, checkpoint,
                                reasons=("unknown event commit state",), config=config_status,
                                dataset=dataset_status)
        if event_status is EventCommitStatus.IN_PROGRESS:
            warnings.append("partially processed event will replay from last committed cursor")
        try:
            IdempotencyLedger(payload.get("committed_idempotency_keys", ()))
        except ValueError as exc:
            return self._report(RecoveryOutcome.RECOVERY_CORRUPTED,
                                RecoveryConfidence.UNSAFE, checkpoint, reasons=(str(exc),),
                                config=config_status, dataset=dataset_status)
        orphan_status, orphan_ids = reconcile_owned_objects(payload)
        ghost_status, ghost_ids = reconcile_ghosts(payload)
        if orphan_status or ghost_status:
            reasons.extend([*(f"orphan:{item}" for item in orphan_ids),
                            *(f"ghost:{item}" for item in ghost_ids)])
            return self._report(RecoveryOutcome.RECOVERY_REQUIRES_MANUAL_REVIEW,
                                RecoveryConfidence.AMBIGUOUS, checkpoint,
                                reasons=tuple(reasons), warnings=tuple(warnings),
                                config=config_status, dataset=dataset_status,
                                orphan=orphan_status, ghost=ghost_status)
        if checkpoint.shutdown_status is ShutdownStatus.UNCLEAN_SHUTDOWN:
            warnings.append("previous shutdown was unclean")
        if self.repository.last_load_used_fallback:
            warnings.append("recovered from previous valid checkpoint")
        state_name = str(payload.get("system_state", "READY"))
        next_epoch = checkpoint.recovery_epoch + (
            1 if checkpoint.shutdown_status is not ShutdownStatus.CLEAN_SHUTDOWN else 0
        )
        if state_name in PROTECTED_STATES:
            return self._report(RecoveryOutcome.RECOVERY_REQUIRES_PROTECTION,
                                RecoveryConfidence.VERIFIED_WITH_WARNINGS, checkpoint,
                                warnings=tuple(warnings), config=config_status,
                                dataset=dataset_status, epoch=next_epoch)
        confidence = RecoveryConfidence.VERIFIED_WITH_WARNINGS if warnings else RecoveryConfidence.DETERMINISTIC
        outcome = RecoveryOutcome.RECOVERY_OK_WITH_WARNINGS if warnings else RecoveryOutcome.RECOVERY_OK
        return self._report(outcome, confidence, checkpoint, warnings=tuple(warnings),
                            config=config_status, dataset=dataset_status, ready=True,
                            epoch=next_epoch)

    def _report(self, outcome: RecoveryOutcome, confidence: RecoveryConfidence,
                checkpoint: Checkpoint | None = None, *, reasons: tuple[str, ...] = (),
                warnings: tuple[str, ...] = (),
                config: ReconciliationStatus = ReconciliationStatus.UNKNOWN,
                dataset: ReconciliationStatus = ReconciliationStatus.UNKNOWN,
                ready: bool = False, epoch: int = 0,
                orphan: ObjectRecoveryStatus | None = None,
                ghost: ObjectRecoveryStatus | None = None) -> RecoveryReport:
        report = RecoveryReport(
            outcome, confidence, checkpoint, reasons, warnings, config, dataset,
            ready, self.repository.last_load_used_fallback, epoch, orphan, ghost,
        )
        self.audit.record("recovery_result", {
            "outcome": outcome.name, "confidence": confidence.name,
            "ready": ready, "recovery_epoch": epoch,
        })
        return report
