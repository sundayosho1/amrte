from datetime import datetime, timedelta, timezone

from amrte.app import build_engine
from amrte.core.clock import FixedClock
from amrte.core.persistence import LocalCheckpointRepository, dataset_fingerprint
from amrte.core.persistence_types import (
    CheckpointRequest, RecoveryConfidence, RecoveryMode, RecoveryOutcome,
    ReconciliationStatus, ShutdownStatus, StorageHealth,
)
from amrte.core.recovery import (
    IdempotencyLedger, RecoveryContext, RecoveryEngine, replay_descriptor,
)
from amrte.infrastructure.local import InMemoryAuditSink, SeededRandomSource


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
DATA = [{"fictional_event": 1}, {"fictional_event": 2}]
FINGERPRINT = dataset_fingerprint(DATA)


def setup(tmp_path, payload=None, shutdown=ShutdownStatus.CLEAN_SHUTDOWN,
          clock_time=NOW):
    clock = FixedClock(clock_time)
    audit = InMemoryAuditSink()
    repo = LocalCheckpointRepository(tmp_path, clock, audit)
    config = build_engine().configuration
    state = {
        "system_state": "READY", "event_status": "COMMITTED",
        "last_committed_sequence": 4, "committed_idempotency_keys": ["EVENT-4"],
        "random_seed": 99, "random_sequence_position": 5,
        "known_owner_ids": [], "objects": [],
        "expected_object_ids": [], "actual_object_ids": [],
    }
    state.update(payload or {})
    req = CheckpointRequest(
        config.schema_version, config.snapshot_id, config.configuration_hash,
        "RESEARCH", "EXPERIMENT-1", "FICTIONAL-DATASET", FINGERPRINT, 2,
        shutdown, state,
    )
    return clock, audit, repo, config, req


def context(config, **overrides):
    values = dict(configuration=config, dataset_id="FICTIONAL-DATASET",
                  dataset_fingerprint=FINGERPRINT, expected_experiment_id="EXPERIMENT-1",
                  recovery_expected=True)
    values.update(overrides)
    return RecoveryContext(**values)


def test_new_run_vs_missing_expected_state(tmp_path):
    clock, audit, repo, config, _ = setup(tmp_path)
    recovery = RecoveryEngine(repo, clock, audit)
    new = recovery.recover(context(config, recovery_expected=False))
    missing = recovery.recover(context(config, recovery_expected=True))
    assert new.outcome is RecoveryOutcome.RECOVERY_NEW_RUN and new.ready
    assert missing.outcome is RecoveryOutcome.RECOVERY_REQUIRES_MANUAL_REVIEW
    assert not missing.ready


def test_clean_valid_recovery(tmp_path):
    clock, audit, repo, config, req = setup(tmp_path)
    repo.save_checkpoint(req)
    report = RecoveryEngine(repo, clock, audit).recover(context(config))
    assert report.outcome is RecoveryOutcome.RECOVERY_OK
    assert report.confidence is RecoveryConfidence.DETERMINISTIC
    assert report.ready and report.recovery_epoch == 2
    assert report.configuration_reconciliation is ReconciliationStatus.MATCH
    assert report.dataset_reconciliation is ReconciliationStatus.MATCH


def test_unclean_restart_partial_event_and_epoch(tmp_path):
    clock, audit, repo, config, req = setup(
        tmp_path, payload={"event_status": "IN_PROGRESS"},
        shutdown=ShutdownStatus.UNCLEAN_SHUTDOWN,
    )
    repo.save_checkpoint(req)
    report = RecoveryEngine(repo, clock, audit).recover(context(config))
    assert report.outcome is RecoveryOutcome.RECOVERY_OK_WITH_WARNINGS
    assert report.recovery_epoch == 3
    assert any("partially processed" in item for item in report.warnings)
    assert any("unclean" in item for item in report.warnings)


def test_configuration_mismatch_fails_closed(tmp_path):
    clock, audit, repo, config, req = setup(tmp_path)
    repo.save_checkpoint(CheckpointRequest(**{**req.__dict__, "configuration_hash": "different"}))
    report = RecoveryEngine(repo, clock, audit).recover(context(config))
    assert report.outcome is RecoveryOutcome.RECOVERY_REQUIRES_MANUAL_REVIEW
    assert report.configuration_reconciliation is ReconciliationStatus.INCOMPATIBLE_CHANGE
    assert not report.ready


def test_dataset_and_experiment_mismatch_fail_closed(tmp_path):
    clock, audit, repo, config, req = setup(tmp_path)
    repo.save_checkpoint(req)
    engine = RecoveryEngine(repo, clock, audit)
    dataset = engine.recover(context(config, dataset_fingerprint="changed"))
    experiment = engine.recover(context(config, expected_experiment_id="OTHER"))
    assert dataset.outcome is RecoveryOutcome.RECOVERY_REQUIRES_MANUAL_REVIEW
    assert experiment.outcome is RecoveryOutcome.RECOVERY_REQUIRES_MANUAL_REVIEW


def test_stale_checkpoint_requires_review(tmp_path):
    clock, audit, repo, config, req = setup(tmp_path, clock_time=NOW)
    repo.save_checkpoint(req)
    later = FixedClock(NOW + timedelta(days=10))
    report = RecoveryEngine(repo, later, audit).recover(
        context(config, maximum_checkpoint_age_seconds=60)
    )
    assert report.outcome is RecoveryOutcome.RECOVERY_REQUIRES_MANUAL_REVIEW


def test_corruption_fallback_reports_warning(tmp_path):
    clock, audit, repo, config, req = setup(tmp_path)
    first = repo.save_checkpoint(req).value
    repo.save_checkpoint(CheckpointRequest(**{**req.__dict__, "state_payload": {
        **req.state_payload, "last_committed_sequence": 5
    }}))
    (tmp_path / repo.CURRENT).write_text("broken", encoding="utf-8")
    report = RecoveryEngine(repo, clock, audit).recover(context(config))
    assert report.ready and report.used_fallback
    assert report.checkpoint.checkpoint_id == first.checkpoint_id


def test_duplicate_idempotency_state_is_corrupted(tmp_path):
    clock, audit, repo, config, req = setup(
        tmp_path, payload={"committed_idempotency_keys": ["X", "X"]}
    )
    repo.save_checkpoint(req)
    report = RecoveryEngine(repo, clock, audit).recover(context(config))
    assert report.outcome is RecoveryOutcome.RECOVERY_CORRUPTED and not report.ready


def test_idempotency_ledger_prevents_duplicate_commit():
    ledger = IdempotencyLedger(["A"])
    assert ledger.is_committed("A")
    assert not ledger.commit("A")
    assert ledger.commit("B")
    assert ledger.snapshot() == ("A", "B")


def test_orphan_and_ghost_state_require_review(tmp_path):
    clock, audit, repo, config, req = setup(tmp_path, payload={
        "known_owner_ids": ["OWNER-1"],
        "objects": [{"id": "OBJECT-1", "owner_id": "MISSING"}],
        "expected_object_ids": ["GHOST-1"], "actual_object_ids": [],
    })
    repo.save_checkpoint(req)
    report = RecoveryEngine(repo, clock, audit).recover(context(config))
    assert report.outcome is RecoveryOutcome.RECOVERY_REQUIRES_MANUAL_REVIEW
    assert report.orphan_status is not None and report.ghost_status is not None


def test_protection_and_suspension_survive_restart(tmp_path):
    for state in ("DEFENSIVE", "PROTECT", "SUSPENDED"):
        state_root = tmp_path / state
        clock, audit, repo, config, req = setup(state_root, payload={
            "system_state": state, "protection_reason": "generic restriction",
            "cooldown_until": "2026-01-02T00:00:00+00:00",
        })
        repo.save_checkpoint(req)
        report = RecoveryEngine(repo, clock, audit).recover(context(config))
        assert report.outcome is RecoveryOutcome.RECOVERY_REQUIRES_PROTECTION
        assert not report.ready
        assert report.checkpoint.state_payload["system_state"] == state


def test_replay_descriptor_preserves_clock_seed_cursor(tmp_path):
    clock, _, repo, _, req = setup(tmp_path, payload={
        "simulation_timestamp": "2025-06-01T12:00:00+00:00",
        "random_seed": 123, "random_sequence_position": 7,
        "last_committed_sequence": 99,
    })
    checkpoint = repo.save_checkpoint(req).value
    replay = replay_descriptor(checkpoint)
    assert replay.seed == 123 and replay.random_sequence_position == 7
    assert replay.event_sequence == 99
    assert checkpoint.state_payload["simulation_timestamp"] == "2025-06-01T12:00:00+00:00"


def test_seeded_random_restore_reproduces_sequence():
    original = SeededRandomSource(42)
    prefix = [original.random() for _ in range(5)]
    continuation = [original.random() for _ in range(3)]
    recovered = SeededRandomSource(0)
    recovered.restore(42, 5)
    assert recovered.position == 5
    assert [recovered.random() for _ in range(3)] == continuation


def test_recovery_disabled_fails_closed(tmp_path):
    clock, audit, repo, config, _ = setup(tmp_path)
    report = RecoveryEngine(repo, clock, audit).recover(context(config), RecoveryMode.RECOVERY_DISABLED)
    assert report.outcome is RecoveryOutcome.RECOVERY_FAILED and not report.ready


def test_explicit_recovery_modes(tmp_path):
    clock, audit, repo, config, _ = setup(tmp_path)
    engine = RecoveryEngine(repo, clock, audit)
    manual = engine.recover(context(config), RecoveryMode.MANUAL_REVIEW_REQUIRED)
    fresh = engine.recover(context(config), RecoveryMode.START_NEW_RUN)
    assert manual.outcome is RecoveryOutcome.RECOVERY_REQUIRES_MANUAL_REVIEW
    assert fresh.outcome is RecoveryOutcome.RECOVERY_NEW_RUN and fresh.ready


def test_unavailable_and_read_only_storage_fail_recovery(tmp_path):
    clock, audit, _, config, _ = setup(tmp_path)
    for health in (StorageHealth.UNAVAILABLE, StorageHealth.READ_ONLY):
        repo = LocalCheckpointRepository(tmp_path / health.name, clock, audit,
                                         availability_override=health)
        report = RecoveryEngine(repo, clock, audit).recover(context(config))
        assert report.outcome is RecoveryOutcome.RECOVERY_FAILED
        assert report.confidence is RecoveryConfidence.UNSAFE
        assert not report.ready
