from fastapi.testclient import TestClient

from amrte.web.app import create_app


def test_health_diagnostics_endpoint_is_read_only():
    app = create_app()

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/health-diagnostics"
        )

        assert response.status_code == 200

        payload = response.json()

        assert payload["mode"] == "READ_ONLY"
        assert payload["research_only"] is True

        assert (
            payload["runtime"]["state"]
            == "RUNNING"
        )

        assert (
            payload["runtime"]["environment"]
            == "RESEARCH"
        )

        assert (
            payload["runtime"]["version"]
            == "0.27.0"
        )

        assert (
            payload["authority"]["health_service"]
            == "HealthService"
        )

        assert (
            payload["authority"]["source"]
            == "engine.registry"
        )

        assert (
            payload["authority"]["parallel_health_engine"]
            is False
        )

        assert (
            payload["authority"]["diagnostic_execution"]
            is False
        )


def test_health_diagnostics_exposes_authoritative_services():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get(
            "/api/v1/health-diagnostics"
        ).json()

        services = payload[
            "mandatory_services"
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

        assert set(services) == expected

        for name in expected:
            assert (
                services[name]["registered"]
                is True
            )

            assert (
                services[name]["status"]
                == "HEALTHY"
            )


def test_health_diagnostics_projects_existing_runtime_evidence():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get(
            "/api/v1/health-diagnostics"
        ).json()

        assert (
            payload["readiness"]["ready"]
            is True
        )

        assert (
            payload["readiness"]["reasons"]
            == []
        )

        assert (
            payload["observability"]["status"]
            == "HEALTHY"
        )

        assert (
            payload["observability"]["chain_valid"]
            is True
        )

        assert (
            payload["persistence"]["repository"]
            == "LocalCheckpointRepository"
        )

        assert (
            payload["persistence"]["storage_health"]
            == "HEALTHY"
        )

        assert (
            payload["persistence"]["chain_valid"]
            is True
        )

        assert (
            payload["recovery"]["ready"]
            is True
        )

        assert (
            payload["recovery"]["epoch"]
            == 0
        )


def test_health_diagnostics_exposes_configuration_identity():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get(
            "/api/v1/health-diagnostics"
        ).json()

        configuration = payload[
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

        assert (
            configuration[
                "validation_status"
            ]
            == "VALID"
        )


def test_health_diagnostics_preserves_execution_boundary():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get(
            "/api/v1/health-diagnostics"
        ).json()

        boundary = payload[
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
            boundary["financial_execution"]
            is False
        )

        assert (
            boundary["broker_connectivity"]
            is False
        )

        assert (
            boundary["account_connectivity"]
            is False
        )


def test_health_diagnostics_declares_no_mutating_capabilities():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get(
            "/api/v1/health-diagnostics"
        ).json()

        capabilities = payload[
            "capabilities"
        ]

        assert (
            capabilities["view_health"]
            is True
        )

        assert (
            capabilities[
                "view_service_status"
            ]
            is True
        )

        assert (
            capabilities[
                "view_observability_health"
            ]
            is True
        )

        assert (
            capabilities[
                "view_persistence_health"
            ]
            is True
        )

        assert (
            capabilities[
                "run_diagnostics"
            ]
            is False
        )

        assert (
            capabilities[
                "resolve_alerts"
            ]
            is False
        )

        assert (
            capabilities[
                "prepare_updates"
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
                "mutate_health"
            ]
            is False
        )


def test_health_diagnostics_rejects_mutation_methods():
    app = create_app()

    with TestClient(app) as client:
        endpoint = (
            "/api/v1/health-diagnostics"
        )

        assert (
            client.post(endpoint).status_code
            == 405
        )

        assert (
            client.put(endpoint).status_code
            == 405
        )

        assert (
            client.patch(endpoint).status_code
            == 405
        )

        assert (
            client.delete(endpoint).status_code
            == 405
        )


def test_health_diagnostics_does_not_expose_sensitive_state():
    app = create_app()

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/health-diagnostics"
        )

        raw = response.text.lower()

        forbidden = (
            "password",
            "credential",
            "api_key",
            "access_token",
            "broker_account",
            "broker_order",
            "live_execution",
            "demo_execution",
            "state_payload",
        )

        for fragment in forbidden:
            assert fragment not in raw
