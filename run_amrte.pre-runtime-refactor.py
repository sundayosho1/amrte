from __future__ import annotations

from amrte.core.observability import JsonLinesSink

import sys
import time
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
from amrte.core.recovery import RecoveryContext, RecoveryEngine


VERSION = "0.27.0"
ENVIRONMENT = "RESEARCH"

STATE_ROOT = Path("data/state")
LOG_PATH = Path("data/logs/amrte.jsonl")

EXPERIMENT_ID = "LOCAL-RESEARCH-RUNTIME"
DATASET_ID = "LOCAL-RESEARCH-NO-DATASET"
DATASET_DESCRIPTOR = [{"source": "local-research-runtime"}]


def main() -> int:
    engine = None
    repository = None
    exit_code = 0

    print("=" * 60)
    print("AMRTE RESEARCH RUNTIME")
    print(f"Version     : {VERSION}")
    print(f"Environment : {ENVIRONMENT}")
    print("Execution   : PROHIBITED")
    print("=" * 60)




    try:
        print("[STARTUP] Configuring persistent observability...")

        persistent_log_sink = JsonLinesSink(
            LOG_PATH,
            maximum_file_bytes=1_000_000,
            maximum_total_bytes=5_000_000,
            rotation_count=3,
        )

        print(f"[OBSERVABILITY] Persistent log: {LOG_PATH}")

        print("[STARTUP] Building AMRTE engine...")

        engine = build_engine(
            ENVIRONMENT,
            additional_sinks=(persistent_log_sink,),
        )

        print(f"[STARTUP] State: {engine.state_machine.state.name}")

        if engine.state_machine.state.name != "READY":
            print("[ERROR] Engine did not reach READY state.")
            exit_code = 1
        else:
            configuration = engine.configuration
            clock = engine.registry.require("clock")
            audit = engine.registry.require("audit")
            random_source = engine.registry.require("random")

            fingerprint = dataset_fingerprint(DATASET_DESCRIPTOR)

            repository = LocalCheckpointRepository(
                STATE_ROOT,
                clock,
                audit,
                maximum_bytes=configuration.values[
                    "persistence.maximum_checkpoint_bytes"
                ],
                retention=configuration.values[
                    "persistence.retention_generations"
                ],
            )

            initialized = repository.initialize()

            if not initialized.success:
                message = (
                    initialized.error.message
                    if initialized.error is not None
                    else "unknown persistence initialization failure"
                )
                print(f"[ERROR] Persistence initialization failed: {message}")
                exit_code = 1
            else:
                print("[PERSISTENCE] Local checkpoint repository ready.")

                existing = repository.latest_valid(
                    quarantine_invalid=True
                )

                recovery_epoch = 0

                if existing.success:
                    print(
                        "[RECOVERY] Checkpoint found: "
                        f"{existing.value.checkpoint_id}"
                    )

                    recovery = RecoveryEngine(
                        repository,
                        clock,
                        audit,
                    )

                    report = recovery.recover(
                        RecoveryContext(
                            configuration,
                            DATASET_ID,
                            fingerprint,
                            EXPERIMENT_ID,
                            True,
                        )
                    )

                    print(
                        f"[RECOVERY] Outcome: "
                        f"{report.outcome.name}"
                    )
                    print(
                        f"[RECOVERY] Confidence: "
                        f"{report.confidence.name}"
                    )

                    if not report.ready:
                        print(
                            "[ERROR] Existing checkpoint "
                            "is not safe for automatic recovery."
                        )
                        exit_code = 1
                    else:
                        recovery_epoch = report.recovery_epoch
                        print(
                            f"[RECOVERY] Epoch: "
                            f"{recovery_epoch}"
                        )

                else:
                    if (
                        existing.error is not None
                        and existing.error.code == "STATE_NOT_FOUND"
                    ):
                        print(
                            "[RECOVERY] No prior checkpoint. "
                            "Starting new local research run."
                        )
                    else:
                        message = (
                            existing.error.message
                            if existing.error is not None
                            else "unknown checkpoint load failure"
                        )
                        print(
                            f"[ERROR] Checkpoint load failed: "
                            f"{message}"
                        )
                        exit_code = 1

                if exit_code == 0:
                    started = engine.start()

                    if not started.success:
                        message = (
                            started.error.message
                            if started.error is not None
                            else "unknown start failure"
                        )
                        print(
                            f"[ERROR] Engine start failed: "
                            f"{message}"
                        )
                        exit_code = 1
                    else:
                        print(
                            f"[RUNTIME] State: "
                            f"{engine.state_machine.state.name}"
                        )
                        print(
                            "[RUNTIME] AMRTE is running in "
                            "local research mode."
                        )
                        print(
                            "[RUNTIME] Financial execution "
                            "is prohibited."
                        )
                        print(
                            "[RUNTIME] Press Ctrl+C "
                            "to stop safely."
                        )

                        while True:
                            time.sleep(1)

    except KeyboardInterrupt:
        print()
        print("[SHUTDOWN] Ctrl+C received.")

    except Exception as exc:
        print(
            f"[FATAL] {type(exc).__name__}: {exc}"
        )
        exit_code = 1

    finally:
        if engine is not None:
            if (
                repository is not None
                and engine.configuration is not None
                and engine.state_machine.state.name
                in {
                    "READY",
                    "RUNNING",
                    "DEFENSIVE",
                    "PROTECT",
                    "SUSPENDED",
                }
            ):
                print("[CHECKPOINT] Saving persistent state...")

                configuration = engine.configuration
                random_source = engine.registry.require("random")

                previous = repository.latest_valid(
                    quarantine_invalid=False
                )

                recovery_epoch = (
                    previous.value.recovery_epoch
                    if previous.success
                    else 0
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
                    recovery_epoch=recovery_epoch,
                    shutdown_status=(
                        ShutdownStatus.CLEAN_SHUTDOWN
                    ),
                    state_payload={
                        "system_state": (
                            engine.state_machine.state.name
                        ),
                        "event_status": "COMMITTED",
                        "last_committed_sequence": 0,
                        "committed_idempotency_keys": [],
                        "random_seed": getattr(
                            random_source,
                            "seed",
                            0,
                        ),
                        "random_sequence_position": getattr(
                            random_source,
                            "position",
                            0,
                        ),
                        "known_owner_ids": [],
                        "objects": [],
                        "expected_object_ids": [],
                        "actual_object_ids": [],
                    },
                )

                saved = repository.save_checkpoint(request)

                if saved.success:
                    print(
                        "[CHECKPOINT] Saved: "
                        f"{saved.value.checkpoint_id}"
                    )
                    print(
                        "[CHECKPOINT] Sequence: "
                        f"{saved.value.sequence_number}"
                    )
                else:
                    message = (
                        saved.error.message
                        if saved.error is not None
                        else "unknown checkpoint failure"
                    )
                    print(
                        f"[CHECKPOINT] Failure: {message}"
                    )
                    exit_code = 1

            print("[SHUTDOWN] Stopping AMRTE...")

            stopped = engine.shutdown(
                "local runtime shutdown"
            )

            if stopped.success:
                print(
                    f"[SHUTDOWN] State: "
                    f"{engine.state_machine.state.name}"
                )
                print("[SHUTDOWN] Complete.")
            else:
                message = (
                    stopped.error.message
                    if stopped.error is not None
                    else "unknown shutdown failure"
                )
                print(
                    f"[SHUTDOWN] Failure: {message}"
                )
                exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())