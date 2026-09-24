from datetime import datetime, timezone

from amrte.app import build_engine
from amrte.core.clock import FixedClock
from amrte.core.persistence import LocalCheckpointRepository, dataset_fingerprint
from amrte.core.persistence_types import CheckpointRequest, ShutdownStatus
from amrte.core.recovery import RecoveryContext, RecoveryEngine
from amrte.core.types import SystemState
from amrte.infrastructure.local import InMemoryAuditSink


def test_integrated_phase1_startup_and_shutdown_are_observable():
    engine = build_engine("RESEARCH")
    names = [name for name, _ in engine.audit.events]
    for expected in ("initialization_started", "runtime_environment_detected",
                     "services_validated", "configuration_loaded", "persistence_loaded",
                     "health_checked", "state_transition"):
        assert expected in names
    assert engine.state_machine.state is SystemState.READY
    assert engine.shutdown("phase-1-test").success
    assert any(event.event_code == "STATE_TRANSITION" for event in engine.observability.events)
    assert engine.observability.verify_chain()


def test_persistence_and_recovery_incident_timeline(tmp_path):
    clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    engine = build_engine(); observer = engine.observability
    audit = InMemoryAuditSink(observer=observer)
    repo = LocalCheckpointRepository(tmp_path, clock, audit)
    config = engine.configuration; fingerprint = dataset_fingerprint([{"fictional": 1}])
    req = CheckpointRequest(config.schema_version, config.snapshot_id,
                            config.configuration_hash, "RESEARCH", "EXP-OBS",
                            "FICTIONAL-DATASET", fingerprint, 0,
                            ShutdownStatus.CLEAN_SHUTDOWN,
                            {"system_state": "READY", "event_status": "COMMITTED",
                             "committed_idempotency_keys": []})
    assert repo.save_checkpoint(req).success
    report = RecoveryEngine(repo, clock, audit).recover(RecoveryContext(
        config, "FICTIONAL-DATASET", fingerprint, "EXP-OBS", True
    ))
    assert report.ready
    codes = {event.event_code for event in observer.events}
    assert "PERSIST_CHECKPOINT_SAVED" in codes and "REC_STARTED" in codes and "REC_COMPLETED" in codes

