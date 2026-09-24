import json
import sys
from pathlib import Path

from amrte.app import build_engine
from amrte.core.persistence import (
    LocalCheckpointRepository,
    dataset_fingerprint,
)
from amrte.core.persistence_types import (
    CheckpointRequest,
    ShutdownStatus,
)
from amrte.operations.runtime import (
    DATASET_DESCRIPTOR,
    DATASET_ID,
    EXPERIMENT_ID,
    ENVIRONMENT,
)

proof_root = Path(sys.argv[1])

engine = build_engine(ENVIRONMENT)

configuration = engine.configuration
clock = engine.registry.require("clock")
audit = engine.registry.require("audit")
random_source = engine.registry.require("random")

repo = LocalCheckpointRepository(
    proof_root,
    clock,
    audit,
    maximum_bytes=configuration.values[
        "persistence.maximum_checkpoint_bytes"
    ],
    retention=configuration.values[
        "persistence.retention_generations"
    ],
)

initialized = repo.initialize()

print(
    "PROOF_REPOSITORY_INITIALIZED="
    + str(initialized.success)
)

if not initialized.success:
    raise SystemExit(20)

before = repo.validate_chain()

print(
    "PROOF_CHAIN_VALID_BEFORE="
    + str(before.success)
)

if before.error is not None:
    print(
        "PROOF_CHAIN_BEFORE_ERROR="
        + before.error.code
    )

existing = repo.latest_valid(
    quarantine_invalid=False
)

print(
    "PROOF_EXISTING_CHECKPOINT_VALID="
    + str(existing.success)
)

if not existing.success:
    if existing.error is not None:
        print(
            "PROOF_EXISTING_ERROR="
            + existing.error.code
        )
    raise SystemExit(21)

base = existing.value

print(
    "PROOF_BASE_CHECKPOINT_ID="
    + str(base.checkpoint_id)
)

print(
    "PROOF_BASE_SEQUENCE="
    + str(base.sequence_number)
)

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
    runtime_environment=engine.environment.name,
    experiment_id=EXPERIMENT_ID,
    dataset_id=DATASET_ID,
    dataset_fingerprint=dataset_fingerprint(
        DATASET_DESCRIPTOR
    ),
    recovery_epoch=base.recovery_epoch,
    shutdown_status=ShutdownStatus.CLEAN_SHUTDOWN,
    state_payload=dict(base.state_payload),
)

saved = repo.save_checkpoint(request)

print(
    "PROOF_SUCCESSOR_SAVE_SUCCESS="
    + str(saved.success)
)

if not saved.success:
    if saved.error is not None:
        print(
            "PROOF_SUCCESSOR_SAVE_ERROR="
            + saved.error.code
        )
    raise SystemExit(22)

successor = saved.value

print(
    "PROOF_SUCCESSOR_CHECKPOINT_ID="
    + str(successor.checkpoint_id)
)

print(
    "PROOF_SUCCESSOR_PREVIOUS_ID="
    + str(successor.previous_checkpoint_id)
)

print(
    "PROOF_SUCCESSOR_SEQUENCE="
    + str(successor.sequence_number)
)

after = repo.validate_chain()

print(
    "PROOF_CHAIN_VALID_AFTER="
    + str(after.success)
)

if after.error is not None:
    print(
        "PROOF_CHAIN_AFTER_ERROR="
        + after.error.code
    )

current_path = (
    proof_root /
    LocalCheckpointRepository.CURRENT
)

previous_path = (
    proof_root /
    LocalCheckpointRepository.PREVIOUS
)

current_raw = json.loads(
    current_path.read_text(
        encoding="utf-8"
    )
)

previous_raw = json.loads(
    previous_path.read_text(
        encoding="utf-8"
    )
)

print(
    "PROOF_DISK_CURRENT_ID="
    + str(current_raw["checkpoint_id"])
)

print(
    "PROOF_DISK_CURRENT_PREVIOUS_ID="
    + str(current_raw["previous_checkpoint_id"])
)

print(
    "PROOF_DISK_PREVIOUS_ID="
    + str(previous_raw["checkpoint_id"])
)

print(
    "PROOF_DIRECT_LINEAGE="
    + str(
        current_raw["previous_checkpoint_id"]
        ==
        previous_raw["checkpoint_id"]
    )
)

print(
    "PROOF_SEQUENCE_INCREASES="
    + str(
        int(current_raw["sequence_number"])
        >
        int(previous_raw["sequence_number"])
    )
)

if not after.success:
    raise SystemExit(23)

if (
    current_raw["previous_checkpoint_id"]
    !=
    previous_raw["checkpoint_id"]
):
    raise SystemExit(24)

if (
    int(current_raw["sequence_number"])
    <=
    int(previous_raw["sequence_number"])
):
    raise SystemExit(25)

print(
    "ISOLATED_AUTHORITY_REPAIR_PROOF=PASS"
)
