from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .constants import AMRTE_VERSION, STATE_SCHEMA_VERSION
from .errors import AMRTEError, Result
from .identity import deterministic_id
from .interfaces import IAuditSink, IClock, IStateRepository
from .persistence_types import (
    Checkpoint, CheckpointRequest, QuarantineRecord, ShutdownStatus,
    StateCompatibility, StorageHealth,
)
from .types import Severity


PERSISTENCE_FORMAT_VERSION = "1.0"
FORBIDDEN_STATE_KEY_FRAGMENTS = (
    "password", "secret", "credential", "api_key", "access_token",
    "broker_account", "broker_order", "live_execution", "demo_execution",
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def dataset_fingerprint(records: Any) -> str:
    """Fingerprint fictional/imported research data without retaining it."""
    return sha256_json(records)


def contains_forbidden_state_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in FORBIDDEN_STATE_KEY_FRAGMENTS):
                return True
            if contains_forbidden_state_key(nested):
                return True
    elif isinstance(value, (list, tuple)):
        return any(contains_forbidden_state_key(item) for item in value)
    return False


def classify_state_schema(version: Any) -> StateCompatibility:
    if not isinstance(version, str) or not version:
        return StateCompatibility.CORRUPTED
    if version == STATE_SCHEMA_VERSION:
        return StateCompatibility.CURRENT
    try:
        current_major = int(STATE_SCHEMA_VERSION.split(".")[0])
        major = int(version.split(".")[0])
    except (ValueError, IndexError):
        return StateCompatibility.CORRUPTED
    if major == current_major:
        return StateCompatibility.COMPATIBLE
    if major < current_major:
        return StateCompatibility.MIGRATION_REQUIRED
    return StateCompatibility.INCOMPATIBLE


class IStateMigration:
    source_version: str
    target_version: str

    def validate_source(self, value: Mapping[str, Any]) -> bool:
        raise NotImplementedError

    def migrate(self, value: Mapping[str, Any]) -> Mapping[str, Any]:
        raise NotImplementedError

    def validate_result(self, value: Mapping[str, Any]) -> bool:
        raise NotImplementedError


class LocalCheckpointRepository(IStateRepository):
    """Authoritative local repository with two crash-consistent generations."""

    CURRENT = "checkpoint.current.json"
    PREVIOUS = "checkpoint.previous.json"
    TEMPORARY = ".checkpoint.pending.tmp"

    def __init__(self, root: Path, clock: IClock, audit: IAuditSink, *,
                 maximum_bytes: int = 1_000_000, retention: int = 2,
                 failure_stage: str | None = None,
                 availability_override: StorageHealth | None = None):
        self.root = Path(root)
        self.clock = clock
        self.audit = audit
        self.maximum_bytes = maximum_bytes
        self.retention = max(2, retention)
        self.failure_stage = failure_stage
        self.availability_override = availability_override
        self.health = StorageHealth.UNKNOWN
        self._last_request: CheckpointRequest | None = None
        self.last_load_used_fallback = False

    def initialize(self) -> Result[None]:
        if self.availability_override is StorageHealth.READ_ONLY:
            self.health = StorageHealth.READ_ONLY
            return self._failure("STORAGE_READ_ONLY", "storage is forced read-only")
        if self.availability_override is StorageHealth.UNAVAILABLE:
            self.health = StorageHealth.UNAVAILABLE
            return self._failure("STORAGE_UNAVAILABLE", "storage is forced unavailable")
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / "quarantine").mkdir(exist_ok=True)
            if not os.access(self.root, os.W_OK):
                self.health = StorageHealth.READ_ONLY
                return self._failure("STORAGE_READ_ONLY", "checkpoint directory is read-only")
            self.health = StorageHealth.HEALTHY
            self._clean_stale_temporary()
            return Result.ok()
        except PermissionError as exc:
            self.health = StorageHealth.READ_ONLY
            return self._failure("STORAGE_PERMISSION_DENIED", str(exc))
        except OSError as exc:
            self.health = StorageHealth.UNAVAILABLE
            return self._failure("STORAGE_UNAVAILABLE", str(exc))

    def save(self, state: Mapping[str, Any]) -> Result[None]:
        if self._last_request is None:
            return self._failure("CHECKPOINT_CONTEXT_REQUIRED", "use save_checkpoint with explicit metadata")
        request = CheckpointRequest(**{**self._last_request.__dict__, "state_payload": dict(state)})
        result = self.save_checkpoint(request)
        return Result.ok() if result.success else Result.fail(result.error)

    def load(self) -> Result[Mapping[str, Any]]:
        result = self.latest_valid(quarantine_invalid=True)
        if not result.success:
            if result.error and result.error.code == "STATE_NOT_FOUND":
                return Result.ok({})
            return Result.fail(result.error)
        return Result.ok(dict(result.value.state_payload))

    def save_checkpoint(self, request: CheckpointRequest) -> Result[Checkpoint]:
        self._last_request = request
        self.audit.record("checkpoint_requested", {"experiment_id": request.experiment_id})
        initialized = self.initialize()
        if not initialized.success:
            return Result.fail(initialized.error)
        previous = self.latest_valid(quarantine_invalid=False)
        sequence = previous.value.sequence_number + 1 if previous.success else 1
        previous_id = previous.value.checkpoint_id if previous.success else None
        try:
            if contains_forbidden_state_key(request.state_payload):
                return self._failure("FORBIDDEN_STATE_FIELD", "checkpoint contains prohibited or sensitive fields")
            checkpoint = self._build_checkpoint(request, sequence, previous_id)
            raw = self._checkpoint_to_dict(checkpoint)
            encoded = canonical_json(raw).encode("utf-8")
            if len(encoded) > self.maximum_bytes:
                return self._failure("STATE_TOO_LARGE", "checkpoint exceeds configured size limit")
            temporary = self.root / self.TEMPORARY
            if self.failure_stage == "temporary_write":
                raise OSError("injected temporary write failure")
            with temporary.open("wb") as handle:
                handle.write(encoded)
                handle.flush()
                if self.failure_stage == "flush":
                    raise OSError("injected flush failure")
                os.fsync(handle.fileno())
            validated = self._load_path(temporary)
            if not validated.success:
                return Result.fail(validated.error)
            self.audit.record("checkpoint_integrity_verified", {
                "checkpoint_id": validated.value.checkpoint_id,
            })
            if self.failure_stage == "promotion":
                raise OSError("injected promotion failure")
            current = self.root / self.CURRENT
            prior_path = self.root / self.PREVIOUS
            if current.exists():
                previous_temp = self.root / ".checkpoint.previous.tmp"
                shutil.copy2(current, previous_temp)
                os.replace(previous_temp, prior_path)
            os.replace(temporary, current)
            self._fsync_directory()
            self.audit.record("checkpoint_promoted", {
                "checkpoint_id": checkpoint.checkpoint_id,
                "previous_retained": prior_path.exists(),
            })
            self.health = StorageHealth.HEALTHY
            self.audit.record("checkpoint_saved", {
                "checkpoint_id": checkpoint.checkpoint_id, "sequence": sequence,
            })
            return Result.ok(checkpoint)
        except (OSError, ValueError, TypeError) as exc:
            self.health = StorageHealth.DEGRADED
            self.audit.record("checkpoint_write_failed", {"reason": str(exc)})
            return self._failure("CHECKPOINT_WRITE_FAILED", str(exc))

    def enumerate_checkpoints(self) -> tuple[Path, ...]:
        return tuple(path for path in (self.root / self.CURRENT, self.root / self.PREVIOUS) if path.exists())

    def latest_valid(self, *, quarantine_invalid: bool = True) -> Result[Checkpoint]:
        self.last_load_used_fallback = False
        paths = self.enumerate_checkpoints()
        if not paths:
            return self._failure("STATE_NOT_FOUND", "no checkpoint exists")
        failures: list[str] = []
        for index, path in enumerate(paths):
            loaded = self._load_path(path)
            if loaded.success:
                self.health = StorageHealth.HEALTHY
                if index > 0:
                    self.last_load_used_fallback = True
                    self.audit.record("checkpoint_fallback", {"path": path.name})
                return loaded
            failures.append(f"{path.name}:{loaded.error.code}")
            if quarantine_invalid:
                self.quarantine(path, loaded.error.message, "FAILED", "UNKNOWN")
        self.health = StorageHealth.CORRUPTED
        return self._failure("NO_VALID_CHECKPOINT", ";".join(failures))

    def validate_chain(self) -> Result[None]:
        current_path, previous_path = self.root / self.CURRENT, self.root / self.PREVIOUS
        if not current_path.exists() or not previous_path.exists():
            return Result.ok(warnings=("checkpoint chain has fewer than two generations",))
        current, previous = self._load_path(current_path), self._load_path(previous_path)
        if not current.success or not previous.success:
            return self._failure("BROKEN_CHECKPOINT_CHAIN", "a chain member is invalid")
        if current.value.previous_checkpoint_id != previous.value.checkpoint_id:
            return self._failure("BROKEN_CHECKPOINT_CHAIN", "previous checkpoint ID does not match")
        if current.value.sequence_number <= previous.value.sequence_number:
            return self._failure("SEQUENCE_REGRESSION", "sequence number did not increase")
        return Result.ok()

    def quarantine(self, path: Path, reason: str, integrity: str,
                   compatibility: str) -> Result[QuarantineRecord]:
        try:
            target = self.root / "quarantine" / f"{path.stem}.{self.clock.now().strftime('%Y%m%dT%H%M%S%fZ')}.json"
            os.replace(path, target)
            record = QuarantineRecord(str(path), str(target), reason, self.clock.now(), integrity, compatibility)
            metadata = target.with_suffix(".metadata.json")
            metadata.write_text(canonical_json({
                "original_path": record.original_path, "reason": reason,
                "timestamp": record.timestamp.isoformat(), "integrity_result": integrity,
                "compatibility_result": compatibility,
            }), encoding="utf-8")
            self.audit.record("checkpoint_quarantined", {"source": path.name, "reason": reason})
            return Result.ok(record)
        except OSError as exc:
            return self._failure("QUARANTINE_FAILED", str(exc))

    def _build_checkpoint(self, request: CheckpointRequest, sequence: int,
                          previous_id: str | None) -> Checkpoint:
        payload = dict(request.state_payload)
        payload_hash = sha256_json(payload)
        created_at = self.clock.now()
        checkpoint_id = deterministic_id("checkpoint", request.experiment_id, sequence,
                                         payload_hash, request.configuration_hash)
        manifest = {
            "checkpoint_id": checkpoint_id, "state_schema_version": STATE_SCHEMA_VERSION,
            "application_version": AMRTE_VERSION, "persistence_format_version": PERSISTENCE_FORMAT_VERSION,
            "configuration_schema_version": request.configuration_schema_version,
            "configuration_snapshot_id": request.configuration_snapshot_id,
            "configuration_hash": request.configuration_hash,
            "runtime_environment": request.runtime_environment,
            "experiment_id": request.experiment_id, "dataset_id": request.dataset_id,
            "dataset_fingerprint": request.dataset_fingerprint, "sequence_number": sequence,
            "recovery_epoch": request.recovery_epoch, "created_at": created_at.isoformat(),
            "previous_checkpoint_id": previous_id, "payload_hash": payload_hash,
            "shutdown_status": request.shutdown_status.name,
        }
        return Checkpoint(
            checkpoint_id, STATE_SCHEMA_VERSION, AMRTE_VERSION,
            request.configuration_schema_version, request.configuration_snapshot_id,
            request.configuration_hash, request.runtime_environment, request.experiment_id,
            request.dataset_id, request.dataset_fingerprint, sequence, request.recovery_epoch,
            created_at, previous_id, payload_hash, sha256_json(manifest),
            request.shutdown_status, payload,
        )

    def _checkpoint_to_dict(self, checkpoint: Checkpoint) -> dict[str, Any]:
        return {
            "checkpoint_id": checkpoint.checkpoint_id,
            "state_schema_version": checkpoint.state_schema_version,
            "application_version": checkpoint.application_version,
            "persistence_format_version": PERSISTENCE_FORMAT_VERSION,
            "configuration_schema_version": checkpoint.configuration_schema_version,
            "configuration_snapshot_id": checkpoint.configuration_snapshot_id,
            "configuration_hash": checkpoint.configuration_hash,
            "runtime_environment": checkpoint.runtime_environment,
            "experiment_id": checkpoint.experiment_id,
            "dataset_id": checkpoint.dataset_id,
            "dataset_fingerprint": checkpoint.dataset_fingerprint,
            "sequence_number": checkpoint.sequence_number,
            "recovery_epoch": checkpoint.recovery_epoch,
            "created_at": checkpoint.created_at.isoformat(),
            "previous_checkpoint_id": checkpoint.previous_checkpoint_id,
            "payload_hash": checkpoint.payload_hash,
            "manifest_hash": checkpoint.manifest_hash,
            "shutdown_status": checkpoint.shutdown_status.name,
            "state_payload": dict(checkpoint.state_payload),
        }

    def _load_path(self, path: Path) -> Result[Checkpoint]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            required = {
                "checkpoint_id", "state_schema_version", "application_version",
                "configuration_schema_version", "configuration_snapshot_id",
                "configuration_hash", "runtime_environment", "experiment_id",
                "dataset_id", "dataset_fingerprint", "sequence_number", "recovery_epoch",
                "created_at", "previous_checkpoint_id", "payload_hash", "manifest_hash",
                "shutdown_status", "state_payload", "persistence_format_version",
            }
            if set(raw) != required:
                raise ValueError("checkpoint fields are missing or unknown")
            if classify_state_schema(raw["state_schema_version"]) not in (
                StateCompatibility.CURRENT, StateCompatibility.COMPATIBLE
            ):
                return self._failure("STATE_SCHEMA_INCOMPATIBLE", raw["state_schema_version"])
            if raw["persistence_format_version"] != PERSISTENCE_FORMAT_VERSION:
                return self._failure("PERSISTENCE_FORMAT_INCOMPATIBLE", raw["persistence_format_version"])
            if sha256_json(raw["state_payload"]) != raw["payload_hash"]:
                return self._failure("PAYLOAD_HASH_MISMATCH", path.name)
            manifest = {key: raw[key] for key in raw if key not in ("manifest_hash", "state_payload")}
            if sha256_json(manifest) != raw["manifest_hash"]:
                return self._failure("MANIFEST_HASH_MISMATCH", path.name)
            checkpoint = Checkpoint(
                raw["checkpoint_id"], raw["state_schema_version"], raw["application_version"],
                raw["configuration_schema_version"], raw["configuration_snapshot_id"],
                raw["configuration_hash"], raw["runtime_environment"], raw["experiment_id"],
                raw["dataset_id"], raw["dataset_fingerprint"], int(raw["sequence_number"]),
                int(raw["recovery_epoch"]), datetime.fromisoformat(raw["created_at"]),
                raw["previous_checkpoint_id"], raw["payload_hash"], raw["manifest_hash"],
                ShutdownStatus[raw["shutdown_status"]], raw["state_payload"],
            )
            return Result.ok(checkpoint)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
            return self._failure("CHECKPOINT_CORRUPTED", str(exc))

    def _clean_stale_temporary(self) -> None:
        temporary = self.root / self.TEMPORARY
        if temporary.exists():
            target = self.root / "quarantine" / f"stale-temporary.{self.clock.now().strftime('%Y%m%dT%H%M%S%fZ')}.tmp"
            os.replace(temporary, target)
            self.audit.record("stale_temporary_quarantined", {"path": target.name})

    def _fsync_directory(self) -> None:        # Directory fsync is a POSIX durability primitive.
        # Windows does not support opening directories with
        # os.open(..., os.O_RDONLY) in the same portable manner.
        if os.name == "nt":
            return

        descriptor = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _failure(self, code: str, message: str):
        return Result.fail(
            AMRTEError(
                self.clock.now(),
                "Core.Persistence",
                "repository",
                Severity.ERROR,
                code,
                message,
                recoverable=True,
            )
        )