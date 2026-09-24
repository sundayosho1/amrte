from pathlib import Path

from fastapi.testclient import TestClient

from amrte.operations.runtime import (
    PersistentResearchRuntime,
)
from amrte.web.app import create_app


def _runtime_factory(
    tmp_path: Path,
):
    state_root = tmp_path / "state"
    log_path = (
        tmp_path
        / "logs"
        / "amrte.jsonl"
    )

    def factory():
        return PersistentResearchRuntime(
            state_root=state_root,
            log_path=log_path,
        )

    return factory


def test_persistence_recovery_api_is_read_only(
    tmp_path,
):
    app = create_app(
        runtime_factory=_runtime_factory(
            tmp_path
        )
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/persistence-recovery"
        )

        assert response.status_code == 200

        payload = response.json()

        assert payload["version"] == "1.0"
        assert payload["mode"] == "READ_ONLY"
        assert payload["research_only"] is True

        assert payload["runtime"]["state"] == "RUNNING"
        assert (
            payload["runtime"]["environment"]
            == "RESEARCH"
        )

        assert (
            payload["authority"]["repository"]
            == "LocalCheckpointRepository"
        )
        assert (
            payload["authority"]["source"]
            == "runtime.repository"
        )
        assert (
            payload["authority"][
                "parallel_repository_created"
            ]
            is False
        )
        assert (
            payload["authority"]["mutation_enabled"]
            is False
        )

        assert "checkpoint" in payload
        assert "lineage" in payload
        assert "chain_integrity" in payload
        assert "persistence_configuration" in payload
        assert "recovery" in payload
        assert "storage" in payload
        assert "recovery_readiness" in payload
        assert "checkpoint_history" in payload
        assert "durability_safeguards" in payload
        assert "capabilities" in payload
        assert "execution_boundary" in payload

        assert (
            payload["chain_integrity"]["valid"]
            is True
        )

        assert (
            payload["persistence_configuration"][
                "retention_generations"
            ]
            >= 2
        )

        assert (
            payload["persistence_configuration"][
                "maximum_checkpoint_bytes"
            ]
            >= 1
        )

        assert (
            payload["recovery"]["recovery_epoch"]
            >= 0
        )

        assert (
            payload["storage"]["checkpoint_count"]
            >= 0
        )

        assert (
            payload["storage"]["state_root"]
            is not None
        )

        assert (
            payload["recovery_readiness"]["ready"]
            is True
        )

        assert isinstance(
            payload["checkpoint_history"],
            list,
        )

        for checkpoint in payload[
            "checkpoint_history"
        ]:
            assert "state_payload" not in checkpoint

        capabilities = payload["capabilities"]

        assert (
            capabilities["checkpoint_observation"]
            is True
        )
        assert (
            capabilities["chain_verification"]
            is True
        )
        assert (
            capabilities["history_observation"]
            is True
        )

        assert (
            capabilities["checkpoint_creation"]
            is False
        )
        assert (
            capabilities["restore"]
            is False
        )
        assert (
            capabilities["rollback"]
            is False
        )
        assert (
            capabilities["quarantine"]
            is False
        )
        assert (
            capabilities["deletion"]
            is False
        )
        assert (
            capabilities["recovery_execution"]
            is False
        )
        assert (
            capabilities[
                "configuration_mutation"
            ]
            is False
        )

        boundary = payload[
            "execution_boundary"
        ]

        assert (
            boundary["capability"]
            == "PROHIBITED"
        )
        assert (
            boundary[
                "financial_execution_available"
            ]
            is False
        )

        for method in (
            "post",
            "put",
            "patch",
            "delete",
        ):
            mutation_response = getattr(
                client,
                method,
            )(
                "/api/v1/persistence-recovery"
            )

            assert (
                mutation_response.status_code
                == 405
            )


def test_persistence_recovery_api_uses_runtime_repository(
    tmp_path,
):
    holder = {}

    state_root = tmp_path / "state"
    log_path = (
        tmp_path
        / "logs"
        / "amrte.jsonl"
    )

    def factory():
        runtime = PersistentResearchRuntime(
            state_root=state_root,
            log_path=log_path,
        )

        holder["runtime"] = runtime

        return runtime

    app = create_app(
        runtime_factory=factory
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/persistence-recovery"
        )

        assert response.status_code == 200

        runtime = holder["runtime"]

        assert runtime.repository is not None

        payload = response.json()

        assert (
            payload["authority"]["repository"]
            == type(
                runtime.repository
            ).__name__
        )

        assert (
            payload["runtime"]["recovery_epoch"]
            == runtime.recovery_epoch
        )


def test_persistence_recovery_api_does_not_expose_state_payload(
    tmp_path,
):
    app = create_app(
        runtime_factory=_runtime_factory(
            tmp_path
        )
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/persistence-recovery"
        )

        assert response.status_code == 200

        serialized = response.text.lower()

        assert "state_payload" not in serialized
        assert "committed_idempotency_keys" not in serialized
        assert "known_owner_ids" not in serialized
        assert "objects" not in serialized
        assert "expected_object_ids" not in serialized
        assert "actual_object_ids" not in serialized
