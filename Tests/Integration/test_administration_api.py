from __future__ import annotations

from fastapi.testclient import TestClient

from amrte.web.app import create_app


def _client():
    return TestClient(
        create_app()
    )


def test_administration_endpoint_exists():
    with _client() as client:
        response = client.get(
            "/api/v1/administration"
        )

        assert response.status_code == 200


def test_administration_is_read_only_research_projection():
    with _client() as client:
        response = client.get(
            "/api/v1/administration"
        )

        assert response.status_code == 200

        body = response.json()

        assert body["mode"] == "READ_ONLY"
        assert body["research_only"] is True


def test_administration_projects_system_identity():
    with _client() as client:
        body = client.get(
            "/api/v1/administration"
        ).json()

        identity = body[
            "system_identity"
        ]

        assert identity["version"] == "0.27.0"
        assert (
            identity["environment"]
            == "RESEARCH"
        )

        assert identity[
            "experiment_id"
        ] == "LOCAL-RESEARCH-RUNTIME"

        assert identity[
            "dataset_id"
        ] == "LOCAL-RESEARCH-NO-DATASET"


def test_administration_projects_configuration_identity():
    with _client() as client:
        body = client.get(
            "/api/v1/administration"
        ).json()

        configuration = body[
            "configuration"
        ]

        assert (
            configuration[
                "snapshot_id"
            ]
            == "CONFIG-BFDCEF6EE22E1395"
        )

        assert (
            configuration[
                "configuration_hash"
            ]
            == (
                "4461634b894399a44c1a3edf33f82d49"
                "bb8ba9034f19332ef2f85d7c590ea507"
            )
        )


def test_administration_projects_registered_services():
    with _client() as client:
        body = client.get(
            "/api/v1/administration"
        ).json()

        services = body[
            "registered_services"
        ]

        expected = {
            "configuration",
            "state",
            "clock",
            "audit",
            "observability",
            "execution",
            "health",
            "random",
        }

        names = {
            item["name"]
            for item in services
        }

        assert expected <= names

        for service in services:
            assert "name" in service
            assert "type" in service


def test_administration_projects_runtime_state():
    with _client() as client:
        body = client.get(
            "/api/v1/administration"
        ).json()

        runtime = body["runtime"]

        assert runtime["state"] == "RUNNING"
        assert (
            runtime["environment"]
            == "RESEARCH"
        )


def test_administration_projects_execution_boundary():
    with _client() as client:
        body = client.get(
            "/api/v1/administration"
        ).json()

        boundary = body[
            "execution_boundary"
        ]

        assert (
            boundary["status"]
            == "PROHIBITED"
        )

        assert (
            boundary["provider"]
            == "ProhibitedExecutionProvider"
        )

        assert (
            boundary[
                "financial_execution"
            ]
            is False
        )

        assert (
            boundary[
                "broker_connectivity"
            ]
            is False
        )

        assert (
            boundary[
                "account_connectivity"
            ]
            is False
        )


def test_administration_projects_persistence_without_mutation():
    with _client() as client:
        body = client.get(
            "/api/v1/administration"
        ).json()

        persistence = body[
            "persistence"
        ]

        assert (
            persistence["repository"]
            == "LocalCheckpointRepository"
        )

        assert (
            persistence["chain_valid"]
            is True
        )

        assert (
            persistence[
                "mutation_allowed"
            ]
            is False
        )


def test_administration_reports_no_dedicated_rbac_authority():
    with _client() as client:
        body = client.get(
            "/api/v1/administration"
        ).json()

        permissions = body[
            "permissions"
        ]

        assert (
            permissions[
                "administration_rbac"
            ]
            is False
        )

        assert (
            permissions[
                "claims_authority"
            ]
            is False
        )

        assert (
            permissions[
                "invented_permissions"
            ]
            is False
        )


def test_administration_capabilities_are_observational_only():
    with _client() as client:
        body = client.get(
            "/api/v1/administration"
        ).json()

        capabilities = body[
            "capabilities"
        ]

        assert (
            capabilities[
                "view_system_identity"
            ]
            is True
        )

        assert (
            capabilities[
                "view_services"
            ]
            is True
        )

        assert (
            capabilities[
                "view_safeguards"
            ]
            is True
        )

        assert (
            capabilities[
                "mutate_configuration"
            ]
            is False
        )

        assert (
            capabilities[
                "register_services"
            ]
            is False
        )

        assert (
            capabilities[
                "mutate_persistence"
            ]
            is False
        )

        assert (
            capabilities[
                "run_diagnostics"
            ]
            is False
        )

        assert (
            capabilities[
                "restore_state"
            ]
            is False
        )

        assert (
            capabilities[
                "enable_execution"
            ]
            is False
        )


def test_administration_rejects_mutation_methods():
    with _client() as client:
        endpoint = (
            "/api/v1/administration"
        )

        for method in (
            "post",
            "put",
            "patch",
            "delete",
        ):
            response = getattr(
                client,
                method,
            )(endpoint)

            assert response.status_code in (
                404,
                405,
            )


def test_administration_does_not_expose_sensitive_state():
    with _client() as client:
        response = client.get(
            "/api/v1/administration"
        )

        text = response.text.lower()

        forbidden = (
            "password",
            "private_key",
            "api_key",
            "access_token",
            "credential",
            "broker_account",
            "broker_order",
            "live_execution",
            "demo_execution",
        )

        for fragment in forbidden:
            assert fragment not in text
