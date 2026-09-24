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

root = Path(sys.argv[1])

expected_current_id = sys.argv[2]
expected_previous_id = sys.argv[3]
expected_sequence = int(sys.argv[4])
expected_successor_id = sys.argv[5]

current_path = (
    root /
    LocalCheckpointRepository.CURRENT
)

previous_path = (
    root /
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

precondition = (
    current_raw["checkpoint_id"]
    ==
    expected_current_id
    and
    previous_raw["checkpoint_id"]
    ==
    expected_current_id
    and
    current_raw["previous_checkpoint_id"]
    ==
    expected_previous_id
    and
    int(current_raw["sequence_number"])
    ==
    expected_sequence
    and
    int(previous_raw["sequence_number"])
    ==
    expected_sequence
)

print(
    "PYTHON_EXACT_PRECONDITION="
    + str(precondition)
)

if not precondition:
    raise SystemExit(30)

engine = build_engine(ENVIRONMENT)

configuration = engine.configuration
clock = engine.registry.require("clock")
audit = engine.registry.require("audit")

repo = LocalCheckpointRepository(
    root,
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
    "REPOSITORY_INITIALIZED="
    + str(initialized.success)
)

if not initialized.success:
    raise SystemExit(31)

existing = repo.latest_valid(
    quarantine_invalid=False
)

print(
    "BASE_CHECKPOINT_VALID="
    + str(existing.success)
)

if not existing.success:
    if existing.error is not None:
        print(
            "BASE_CHECKPOINT_ERROR="
            + existing.error.code
        )
    raise SystemExit(32)

base = existing.value

print(
    "BASE_CHECKPOINT_ID="
    + str(base.checkpoint_id)
)

print(
    "BASE_SEQUENCE="
    + str(base.sequence_number)
)

if (
    base.checkpoint_id
    !=
    expected_current_id
):
    raise SystemExit(33)

if (
    int(base.sequence_number)
    !=
    expected_sequence
):
    raise SystemExit(34)

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
    "PRODUCTION_SAVE_SUCCESS="
    + str(saved.success)
)

if not saved.success:
    if saved.error is not None:
        print(
            "PRODUCTION_SAVE_ERROR="
            + saved.error.code
        )
    raise SystemExit(35)

successor = saved.value

print(
    "SUCCESSOR_ID="
    + str(successor.checkpoint_id)
)

print(
    "SUCCESSOR_PREVIOUS_ID="
    + str(successor.previous_checkpoint_id)
)

print(
    "SUCCESSOR_SEQUENCE="
    + str(successor.sequence_number)
)

expected_identity = (
    successor.checkpoint_id
    ==
    expected_successor_id
)

print(
    "EXPECTED_SUCCESSOR_ID_MATCH="
    + str(expected_identity)
)

chain = repo.validate_chain()

print(
    "PRODUCTION_CHAIN_VALID="
    + str(chain.success)
)

if chain.error is not None:
    print(
        "PRODUCTION_CHAIN_ERROR="
        + chain.error.code
    )

current_after = json.loads(
    current_path.read_text(
        encoding="utf-8"
    )
)

previous_after = json.loads(
    previous_path.read_text(
        encoding="utf-8"
    )
)

direct_lineage = (
    current_after["previous_checkpoint_id"]
    ==
    previous_after["checkpoint_id"]
)

sequence_increase = (
    int(current_after["sequence_number"])
    >
    int(previous_after["sequence_number"])
)

base_preserved = (
    previous_after["checkpoint_id"]
    ==
    expected_current_id
)

print(
    "DIRECT_LINEAGE_VALID="
    + str(direct_lineage)
)

print(
    "SEQUENCE_INCREASE_VALID="
    + str(sequence_increase)
)

print(
    "BASE_PRESERVED_AS_PREVIOUS="
    + str(base_preserved)
)

if not expected_identity:
    raise SystemExit(36)

if not chain.success:
    raise SystemExit(37)

if not direct_lineage:
    raise SystemExit(38)

if not sequence_increase:
    raise SystemExit(39)

if not base_preserved:
    raise SystemExit(40)

print(
    "AUTHORITY_BASED_PRODUCTION_REPAIR=PASS"
)
