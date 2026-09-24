from datetime import datetime, timezone

from amrte.app import build_engine
from amrte.core.clock import FixedClock
from amrte.core.persistence import LocalCheckpointRepository, dataset_fingerprint
from amrte.core.persistence_types import CheckpointRequest, RecoveryOutcome, ShutdownStatus, StorageHealth
from amrte.core.recovery import RecoveryContext, RecoveryEngine
from amrte.core.types import Capability
from amrte.infrastructure.local import InMemoryAuditSink


def test_checkpoint_restart_recovery_readiness_and_safety(tmp_path):
    clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    audit = InMemoryAuditSink()
    repo = LocalCheckpointRepository(tmp_path, clock, audit)
    application = build_engine()
    config = application.configuration
    fingerprint = dataset_fingerprint([{"fictional": 1}])
    request = CheckpointRequest(
        config.schema_version, config.snapshot_id, config.configuration_hash,
        "RESEARCH", "EXPERIMENT-INTEGRATION", "FICTIONAL-DATASET", fingerprint,
        0, ShutdownStatus.CLEAN_SHUTDOWN,
        {"system_state": "READY", "event_status": "COMMITTED",
         "committed_idempotency_keys": [], "last_committed_sequence": 1},
    )
    assert repo.save_checkpoint(request).success
    restarted_repo = LocalCheckpointRepository(tmp_path, clock, audit)
    report = RecoveryEngine(restarted_repo, clock, audit).recover(RecoveryContext(
        config, "FICTIONAL-DATASET", fingerprint, "EXPERIMENT-INTEGRATION", True
    ))
    assert report.outcome is RecoveryOutcome.RECOVERY_OK and report.ready
    assert restarted_repo.health is StorageHealth.HEALTHY
    assert not application.capabilities.has(Capability.LIVE_BROKER_EXECUTION_AVAILABLE)
    assert not application.capabilities.has(Capability.DEMO_BROKER_EXECUTION_AVAILABLE)

