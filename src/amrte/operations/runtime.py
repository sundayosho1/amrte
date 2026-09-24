from __future__ import annotations

from pathlib import Path

from amrte.app import build_engine
from amrte.core.constants import AMRTE_VERSION
from amrte.core.observability import JsonLinesSink
from amrte.core.persistence import (
    LocalCheckpointRepository,
    dataset_fingerprint,
)
from amrte.core.persistence_types import (
    CheckpointRequest,
    RecoveryReport,
    ShutdownStatus,
)
from amrte.core.recovery import RecoveryContext, RecoveryEngine


VERSION = AMRTE_VERSION
ENVIRONMENT = "RESEARCH"

DEFAULT_STATE_ROOT = Path("data/state")
DEFAULT_LOG_PATH = Path("data/logs/amrte.jsonl")

EXPERIMENT_ID = "LOCAL-RESEARCH-RUNTIME"
DATASET_ID = "LOCAL-RESEARCH-NO-DATASET"
DATASET_DESCRIPTOR = ({"source": "local-research-runtime"},)


class PersistentResearchRuntime:
    """Reusable persistent host lifecycle for local AMRTE research."""

    def __init__(
        self,
        *,
        state_root: Path = DEFAULT_STATE_ROOT,
        log_path: Path = DEFAULT_LOG_PATH,
    ) -> None:
        self.state_root = Path(state_root)
        self.log_path = Path(log_path)

        self.engine = None
        self.repository: LocalCheckpointRepository | None = None
        self.recovery_report: RecoveryReport | None = None
        self.last_checkpoint = None
        self.recovery_epoch = 0

    @property
    def state(self) -> str:
        if self.engine is None:
            return "NOT_STARTED"
        return self.engine.state_machine.state.name

    @property
    def composition(self):
        if self.engine is None:
            return None
        return getattr(self.engine, "composition", None)

    def start(self) -> None:
        if self.engine is not None:
            raise RuntimeError("AMRTE runtime has already been started")

        persistent_log_sink = JsonLinesSink(
            self.log_path,
            maximum_file_bytes=1_000_000,
            maximum_total_bytes=5_000_000,
            rotation_count=3,
        )

        engine = build_engine(
            ENVIRONMENT,
            additional_sinks=(persistent_log_sink,),
        )

        self.engine = engine

        if engine.state_machine.state.name != "READY":
            raise RuntimeError(
                "AMRTE engine did not reach READY state"
            )

        configuration = engine.configuration
        clock = engine.registry.require("clock")
        audit = engine.registry.require("audit")

        repository = LocalCheckpointRepository(
            self.state_root,
            clock,
            audit,
            maximum_bytes=configuration.values[
                "persistence.maximum_checkpoint_bytes"
            ],
            retention=configuration.values[
                "persistence.retention_generations"
            ],
        )

        self.repository = repository

        initialized = repository.initialize()

        if not initialized.success:
            message = (
                initialized.error.message
                if initialized.error is not None
                else "unknown persistence initialization failure"
            )
            raise RuntimeError(
                f"persistence initialization failed: {message}"
            )

        existing = repository.latest_valid(
            quarantine_invalid=True
        )

        if existing.success:
            recovery = RecoveryEngine(
                repository,
                clock,
                audit,
            )

            report = recovery.recover(
                RecoveryContext(
                    configuration,
                    DATASET_ID,
                    dataset_fingerprint(DATASET_DESCRIPTOR),
                    EXPERIMENT_ID,
                    True,
                )
            )

            self.recovery_report = report

            if not report.ready:
                raise RuntimeError(
                    "existing checkpoint is not safe for "
                    "automatic recovery: "
                    + "; ".join(report.reasons)
                )

            if report.checkpoint is None:
                raise RuntimeError(
                    "ready recovery report does not "
                    "contain a checkpoint"
                )

            self.last_checkpoint = report.checkpoint
            self.recovery_epoch = report.recovery_epoch

        else:
            if (
                existing.error is None
                or existing.error.code != "STATE_NOT_FOUND"
            ):
                message = (
                    existing.error.message
                    if existing.error is not None
                    else "unknown checkpoint load failure"
                )
                raise RuntimeError(
                    f"checkpoint load failed: {message}"
                )

            self.recovery_epoch = 0

        started = engine.start()

        if not started.success:
            message = (
                started.error.message
                if started.error is not None
                else "unknown engine start failure"
            )
            raise RuntimeError(
                f"engine start failed: {message}"
            )

    def checkpoint(self):
        if self.engine is None or self.repository is None:
            raise RuntimeError("AMRTE runtime is not initialized")

        configuration = self.engine.configuration

        if configuration is None:
            raise RuntimeError(
                "AMRTE configuration is unavailable"
            )

        random_source = self.engine.registry.require("random")

        recovery_epoch = self.recovery_epoch

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
            runtime_environment=self.engine.environment.name,
            experiment_id=EXPERIMENT_ID,
            dataset_id=DATASET_ID,
            dataset_fingerprint=dataset_fingerprint(
                DATASET_DESCRIPTOR
            ),
            recovery_epoch=recovery_epoch,
            shutdown_status=ShutdownStatus.CLEAN_SHUTDOWN,
            state_payload={
                "system_state": (
                    self.engine.state_machine.state.name
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

        saved = self.repository.save_checkpoint(request)

        if not saved.success:
            message = (
                saved.error.message
                if saved.error is not None
                else "unknown checkpoint failure"
            )
            raise RuntimeError(
                f"checkpoint save failed: {message}"
            )

        self.last_checkpoint = saved.value
        return saved.value

    def shutdown(self) -> None:
        if self.engine is None:
            return

        if self.engine.state_machine.state.name == "STOPPED":
            return

        if (
            self.repository is not None
            and self.engine.configuration is not None
            and self.engine.state_machine.state.name
            in {
                "READY",
                "RUNNING",
                "DEFENSIVE",
                "PROTECT",
                "SUSPENDED",
            }
        ):
            self.checkpoint()

        stopped = self.engine.shutdown(
            "persistent research runtime shutdown"
        )

        if not stopped.success:
            message = (
                stopped.error.message
                if stopped.error is not None
                else "unknown shutdown failure"
            )
            raise RuntimeError(
                f"engine shutdown failed: {message}"
            )
