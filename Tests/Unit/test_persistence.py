from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from amrte.core.clock import FixedClock
from amrte.core.persistence import (
    LocalCheckpointRepository, canonical_json, classify_state_schema,
    dataset_fingerprint, sha256_json,
)
from amrte.core.persistence_types import (
    CheckpointRequest, ShutdownStatus, StateCompatibility, StorageHealth,
)
from amrte.infrastructure.local import InMemoryAuditSink


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def repository(tmp_path, **kwargs):
    return LocalCheckpointRepository(tmp_path, FixedClock(NOW), InMemoryAuditSink(), **kwargs)


def request(sequence_value=1, **overrides):
    values = dict(
        configuration_schema_version="1.0",
        configuration_snapshot_id="CONFIG-1",
        configuration_hash="config-hash",
        runtime_environment="RESEARCH",
        experiment_id="EXPERIMENT-1",
        dataset_id="FICTIONAL-DATASET",
        dataset_fingerprint=dataset_fingerprint([{"event": 1}]),
        recovery_epoch=0,
        shutdown_status=ShutdownStatus.CLEAN_SHUTDOWN,
        state_payload={
            "system_state": "READY",
            "last_committed_sequence": sequence_value,
            "event_status": "COMMITTED",
            "committed_idempotency_keys": [f"EVENT-{sequence_value}"],
            "random_seed": 77,
            "random_sequence_position": 3,
        },
    )
    values.update(overrides)
    return CheckpointRequest(**values)


def test_first_start_has_no_prior_state(tmp_path):
    repo = repository(tmp_path)
    assert repo.initialize().success
    result = repo.latest_valid()
    assert not result.success and result.error.code == "STATE_NOT_FOUND"
    assert repo.load().success and repo.load().value == {}


def test_save_load_integrity_and_explicit_metadata(tmp_path):
    repo = repository(tmp_path)
    saved = repo.save_checkpoint(request())
    assert saved.success and saved.value.sequence_number == 1
    loaded = repo.latest_valid()
    assert loaded.success and loaded.value.checkpoint_id == saved.value.checkpoint_id
    assert loaded.value.payload_hash == sha256_json(dict(loaded.value.state_payload))
    assert repo.health is StorageHealth.HEALTHY


def test_generations_sequence_and_chain(tmp_path):
    repo = repository(tmp_path)
    first = repo.save_checkpoint(request(1)).value
    second = repo.save_checkpoint(request(2)).value
    assert second.sequence_number == 2
    assert second.previous_checkpoint_id == first.checkpoint_id
    assert len(repo.enumerate_checkpoints()) == 2
    assert repo.validate_chain().success


def test_corrupted_current_falls_back_and_quarantines(tmp_path):
    repo = repository(tmp_path)
    first = repo.save_checkpoint(request(1)).value
    repo.save_checkpoint(request(2))
    (tmp_path / repo.CURRENT).write_text("{corrupted", encoding="utf-8")
    loaded = repo.latest_valid(quarantine_invalid=True)
    assert loaded.success and loaded.value.checkpoint_id == first.checkpoint_id
    assert repo.last_load_used_fallback
    assert list((tmp_path / "quarantine").glob("*.json"))


def test_both_generations_corrupted_fail_closed(tmp_path):
    repo = repository(tmp_path)
    repo.save_checkpoint(request(1)); repo.save_checkpoint(request(2))
    for path in repo.enumerate_checkpoints(): path.write_text("bad", encoding="utf-8")
    result = repo.latest_valid()
    assert not result.success and result.error.code == "NO_VALID_CHECKPOINT"
    assert repo.health is StorageHealth.CORRUPTED


def test_payload_and_manifest_tampering_detected(tmp_path):
    repo = repository(tmp_path)
    repo.save_checkpoint(request())
    path = tmp_path / repo.CURRENT
    raw = json.loads(path.read_text())
    raw["state_payload"]["system_state"] = "CHANGED"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert repo._load_path(path).error.code == "PAYLOAD_HASH_MISMATCH"


def test_incompatible_and_migration_required_schema_rejected(tmp_path):
    repo = repository(tmp_path)
    repo.save_checkpoint(request())
    path = tmp_path / repo.CURRENT
    raw = json.loads(path.read_text())
    raw["state_schema_version"] = "2.0"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert repo._load_path(path).error.code == "STATE_SCHEMA_INCOMPATIBLE"
    assert classify_state_schema("0.9") is StateCompatibility.MIGRATION_REQUIRED
    assert classify_state_schema("1.7") is StateCompatibility.COMPATIBLE
    assert classify_state_schema(None) is StateCompatibility.CORRUPTED


@pytest.mark.parametrize("stage", ["temporary_write", "flush", "promotion"])
def test_injected_write_failures_preserve_last_valid(tmp_path, stage):
    repo = repository(tmp_path)
    first = repo.save_checkpoint(request(1)).value
    repo.failure_stage = stage
    failed = repo.save_checkpoint(request(2))
    assert not failed.success and repo.health is StorageHealth.DEGRADED
    repo.failure_stage = None
    loaded = repo.latest_valid()
    assert loaded.success and loaded.value.checkpoint_id == first.checkpoint_id


def test_state_size_limit(tmp_path):
    repo = repository(tmp_path, maximum_bytes=500)
    large = request(state_payload={"blob": "x" * 1000})
    result = repo.save_checkpoint(large)
    assert not result.success and result.error.code == "STATE_TOO_LARGE"


def test_stale_temporary_file_is_quarantined(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / LocalCheckpointRepository.TEMPORARY).write_text("partial", encoding="utf-8")
    repo = repository(tmp_path)
    assert repo.initialize().success
    assert not (tmp_path / repo.TEMPORARY).exists()
    assert list((tmp_path / "quarantine").glob("stale-temporary*.tmp"))


def test_canonical_serialization_and_dataset_fingerprint_are_deterministic():
    assert canonical_json({"b": 2, "a": 1}) == canonical_json({"a": 1, "b": 2})
    assert dataset_fingerprint([{"b": 2, "a": 1}]) == dataset_fingerprint([{"a": 1, "b": 2}])


def test_generic_save_requires_checkpoint_context(tmp_path):
    repo = repository(tmp_path)
    result = repo.save({"x": 1})
    assert not result.success and result.error.code == "CHECKPOINT_CONTEXT_REQUIRED"


def test_sensitive_or_execution_enabling_state_is_rejected(tmp_path):
    repo = repository(tmp_path)
    for payload in ({"api_key": "x"}, {"broker_account": "x"}, {"live_execution": True}):
        result = repo.save_checkpoint(request(state_payload=payload))
        assert not result.success and result.error.code == "FORBIDDEN_STATE_FIELD"
