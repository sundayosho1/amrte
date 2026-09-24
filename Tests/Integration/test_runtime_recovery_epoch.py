from datetime import datetime, timezone

from amrte.app import build_engine
from amrte.core.clock import FixedClock
from amrte.core.persistence import (
    LocalCheckpointRepository,
    dataset_fingerprint,
)
from amrte.core.persistence_types import (
    CheckpointRequest,
    ShutdownStatus,
)
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.operations.runtime import (
    DATASET_DESCRIPTOR,
    DATASET_ID,
    EXPERIMENT_ID,
    PersistentResearchRuntime,
)


def test_runtime_checkpoint_preserves_incremented_recovery_epoch(
    tmp_path,
):
    """
    A checkpoint written after an unclean recovery must persist
    the incremented runtime recovery epoch rather than copying
    the stale epoch from the recovered checkpoint.
    """

    state_root = tmp_path / "state"
    log_path = tmp_path / "logs" / "amrte.jsonl"

    clock = FixedClock(
        datetime(
            2026,
            1,
            1,
            tzinfo=timezone.utc,
        )
    )

    audit = InMemoryAuditSink()

    repository = LocalCheckpointRepository(
        state_root,
        clock,
        audit,
    )

    runtime = PersistentResearchRuntime(
        state_root=state_root,
        log_path=log_path,
    )

    configuration = build_engine().configuration

    assert configuration is not None

    request = CheckpointRequest(
        configuration_schema_version=(
            configuration.schema_version
        ),
        configuration_snapshot_id=(
            configuration.snapshot_id
        ),
        configuration_hash=(
            configuration.configuration_hash
        ),
        runtime_environment="RESEARCH",
        experiment_id=EXPERIMENT_ID,
        dataset_id=DATASET_ID,
        dataset_fingerprint=dataset_fingerprint(
            DATASET_DESCRIPTOR
        ),
        recovery_epoch=2,
        shutdown_status=(
            ShutdownStatus.UNCLEAN_SHUTDOWN
        ),
        state_payload={
            "system_state": "READY",
            "event_status": "COMMITTED",
            "last_committed_sequence": 0,
            "committed_idempotency_keys": [],
            "random_seed": 20260919,
            "random_sequence_position": 0,
            "known_owner_ids": [],
            "objects": [],
            "expected_object_ids": [],
            "actual_object_ids": [],
        },
    )

    saved = repository.save_checkpoint(
        request
    )

    assert saved.success

    runtime.start()

    try:

        assert runtime.recovery_report is not None

        assert (
            runtime.recovery_report.recovery_epoch
            == 3
        )

        assert runtime.recovery_epoch == 3

        checkpoint = runtime.checkpoint()

        assert checkpoint.recovery_epoch == 3

        assert runtime.last_checkpoint is not None

        assert (
            runtime.last_checkpoint.recovery_epoch
            == 3
        )

    finally:

        runtime.shutdown()
