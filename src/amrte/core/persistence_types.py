from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from types import MappingProxyType
from typing import Any, Mapping


class StateCompatibility(Enum):
    CURRENT = auto()
    COMPATIBLE = auto()
    MIGRATION_REQUIRED = auto()
    INCOMPATIBLE = auto()
    CORRUPTED = auto()
    UNKNOWN = auto()


class StorageHealth(Enum):
    HEALTHY = auto()
    DEGRADED = auto()
    READ_ONLY = auto()
    UNAVAILABLE = auto()
    CORRUPTED = auto()
    UNKNOWN = auto()


class ShutdownStatus(Enum):
    CLEAN_SHUTDOWN = auto()
    UNCLEAN_SHUTDOWN = auto()
    UNKNOWN_SHUTDOWN = auto()


class EventCommitStatus(Enum):
    NOT_STARTED = auto()
    IN_PROGRESS = auto()
    COMMITTED = auto()


class RecoveryMode(Enum):
    AUTO_SAFE = auto()
    MANUAL_REVIEW_REQUIRED = auto()
    START_NEW_RUN = auto()
    RECOVERY_DISABLED = auto()


class RecoveryOutcome(Enum):
    RECOVERY_OK = auto()
    RECOVERY_OK_WITH_WARNINGS = auto()
    RECOVERY_NEW_RUN = auto()
    RECOVERY_REQUIRES_PROTECTION = auto()
    RECOVERY_REQUIRES_MANUAL_REVIEW = auto()
    RECOVERY_INCOMPATIBLE = auto()
    RECOVERY_CORRUPTED = auto()
    RECOVERY_FAILED = auto()


class RecoveryConfidence(Enum):
    DETERMINISTIC = auto()
    VERIFIED_WITH_WARNINGS = auto()
    AMBIGUOUS = auto()
    UNSAFE = auto()


class ReconciliationStatus(Enum):
    MATCH = auto()
    COMPATIBLE_CHANGE = auto()
    INCOMPATIBLE_CHANGE = auto()
    UNKNOWN = auto()


class ObjectRecoveryStatus(Enum):
    RECONSTRUCTED = auto()
    QUARANTINED = auto()
    MANUAL_REVIEW = auto()
    RECOVERY_FAILED = auto()


@dataclass(frozen=True)
class Checkpoint:
    checkpoint_id: str
    state_schema_version: str
    application_version: str
    configuration_schema_version: str
    configuration_snapshot_id: str
    configuration_hash: str
    runtime_environment: str
    experiment_id: str
    dataset_id: str
    dataset_fingerprint: str
    sequence_number: int
    recovery_epoch: int
    created_at: datetime
    previous_checkpoint_id: str | None
    payload_hash: str
    manifest_hash: str
    shutdown_status: ShutdownStatus
    state_payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "state_payload", MappingProxyType(dict(self.state_payload)))


@dataclass(frozen=True)
class CheckpointRequest:
    configuration_schema_version: str
    configuration_snapshot_id: str
    configuration_hash: str
    runtime_environment: str
    experiment_id: str
    dataset_id: str
    dataset_fingerprint: str
    recovery_epoch: int
    shutdown_status: ShutdownStatus
    state_payload: Mapping[str, Any]


@dataclass(frozen=True)
class QuarantineRecord:
    original_path: str
    quarantined_path: str
    reason: str
    timestamp: datetime
    integrity_result: str
    compatibility_result: str


@dataclass(frozen=True)
class RecoveryReport:
    outcome: RecoveryOutcome
    confidence: RecoveryConfidence
    checkpoint: Checkpoint | None = None
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    configuration_reconciliation: ReconciliationStatus = ReconciliationStatus.UNKNOWN
    dataset_reconciliation: ReconciliationStatus = ReconciliationStatus.UNKNOWN
    ready: bool = False
    used_fallback: bool = False
    recovery_epoch: int = 0
    orphan_status: ObjectRecoveryStatus | None = None
    ghost_status: ObjectRecoveryStatus | None = None


@dataclass(frozen=True)
class ReplayDescriptor:
    application_version: str
    configuration_hash: str
    dataset_fingerprint: str
    starting_checkpoint_id: str
    seed: int
    random_sequence_position: int
    event_sequence: int

