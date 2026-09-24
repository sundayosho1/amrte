from fastapi.testclient import TestClient

from amrte.web.app import app


EXPECTED_DOMAINS = {
    "runtime_lifecycle",
    "persistence_recovery",
    "observability",
    "health_diagnostics",
    "windows_host",
    "research_safety",
}

ALLOWED_EVIDENCE_STATES = {
    "IMPLEMENTED",
    "CONFIGURED",
    "OBSERVED",
    "QUALIFIED",
    "UNAVAILABLE",
    "NOT_VERIFIED",
}


def test_operational_readiness_endpoint_is_reachable():
    with TestClient(app) as client:
        response = client.get("/api/v1/operational-readiness")

    assert response.status_code == 200


def test_operational_readiness_contract_is_explicit_and_bounded():
    with TestClient(app) as client:
        response = client.get("/api/v1/operational-readiness")

    assert response.status_code == 200

    payload = response.json()

    assert payload["product"] == (
        "Operational Readiness & Evidence Console"
    )

    assert payload["environment"] == "RESEARCH"
    assert payload["read_only"] is True

    assert set(payload["domains"]) == EXPECTED_DOMAINS

    for domain_name, domain in payload["domains"].items():
        assert domain_name in EXPECTED_DOMAINS
        assert domain["evidence_state"] in ALLOWED_EVIDENCE_STATES
        assert isinstance(domain["evidence"], list)
        assert isinstance(domain["limitations"], list)


def test_runtime_authority_is_reported_without_parallel_owner():
    with TestClient(app) as client:
        payload = client.get(
            "/api/v1/operational-readiness"
        ).json()

    runtime = payload["runtime_authority"]

    assert runtime["authority"] == "PersistentResearchRuntime"
    assert runtime["parallel_runtime_authority"] is False
    assert runtime["web_lifecycle_owner"] == "FastAPI lifespan"
    assert runtime["cli_host"] == "run_amrte.py"


def test_execution_boundary_remains_research_only():
    with TestClient(app) as client:
        payload = client.get(
            "/api/v1/operational-readiness"
        ).json()

    boundary = payload["execution_boundary"]

    assert boundary["status"] == "PROHIBITED"
    assert (
        boundary["provider"]
        == "ProhibitedExecutionProvider"
    )

    assert boundary["financial_execution"] is False
    assert boundary["broker_connectivity"] is False
    assert boundary["account_connectivity"] is False


def test_windows_native_qualification_is_not_fabricated():
    with TestClient(app) as client:
        payload = client.get(
            "/api/v1/operational-readiness"
        ).json()

    windows = payload["domains"]["windows_host"]

    assert windows["native_windows_qualification"] is False
    assert windows["evidence_state"] in {
        "IMPLEMENTED",
        "CONFIGURED",
        "OBSERVED",
        "NOT_VERIFIED",
    }

    assert windows["evidence_state"] != "QUALIFIED"

    assert any(
        "native Windows" in limitation
        or "Windows service" in limitation
        for limitation in windows["limitations"]
    )


def test_deployment_diagnostics_is_not_claimed_as_runtime_authority():
    with TestClient(app) as client:
        payload = client.get(
            "/api/v1/operational-readiness"
        ).json()

    deployment = payload["deployment_diagnostics"]

    assert (
        deployment["implementation"]
        == "DeploymentDiagnosticsEngine"
    )

    assert deployment["runtime_authority"] is False
    assert deployment["runtime_active"] is False
    assert deployment["current_state_available"] is False


def test_operational_readiness_does_not_expose_mutation_methods():
    with TestClient(app) as client:
        for method in (
            client.post,
            client.put,
            client.patch,
            client.delete,
        ):
            response = method(
                "/api/v1/operational-readiness"
            )

            assert response.status_code == 405


def test_readiness_contract_does_not_expose_process_controls():
    with TestClient(app) as client:
        payload = client.get(
            "/api/v1/operational-readiness"
        ).json()

    forbidden_keys = {
        "start",
        "stop",
        "restart",
        "kill",
        "terminate",
        "execute",
        "run",
        "resume",
        "shutdown",
    }

    def walk(value):
        if isinstance(value, dict):
            for key, nested in value.items():
                assert key.lower() not in forbidden_keys
                walk(nested)

        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(payload)
