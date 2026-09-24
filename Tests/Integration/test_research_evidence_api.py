from fastapi.testclient import TestClient

from amrte.web.app import app


ENDPOINT = "/api/v1/research-evidence"


EXPECTED_CAPABILITIES = {
    "research_performance_analytics",
    "deterministic_experiments",
    "robustness_validation",
    "research_lifecycle",
    "observation_quality",
    "research_reliability",
    "temporal_quality_protection",
    "system_safety",
}


FORBIDDEN_FRAGMENTS = (
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


def _get():
    with TestClient(app) as client:
        response = client.get(ENDPOINT)
        return response


def test_research_evidence_endpoint_exists():
    response = _get()

    assert response.status_code == 200


def test_research_evidence_is_read_only_research_projection():
    payload = _get().json()

    assert payload["mode"] == "READ_ONLY"
    assert payload["research_only"] is True
    assert payload["authority"]["projection_only"] is True
    assert payload["authority"]["new_runtime_authority"] is False
    assert payload["authority"]["target_engine_instantiation"] is False


def test_research_evidence_reports_all_discovered_capabilities():
    payload = _get().json()

    capabilities = payload["research_capabilities"]

    names = {
        item["capability"]
        for item in capabilities
    }

    assert names == EXPECTED_CAPABILITIES
    assert len(capabilities) == 8


def test_capabilities_are_not_claimed_runtime_active():
    payload = _get().json()

    for item in payload["research_capabilities"]:
        assert item["implemented"] is True
        assert item["runtime_authority"] is False
        assert item["runtime_active"] is False


def test_unavailable_evidence_is_explicit_not_fabricated():
    payload = _get().json()

    for item in payload["research_capabilities"]:
        assert item["evidence_available"] is False
        assert item["status"] == "AVAILABLE_NOT_ACTIVATED"


def test_no_research_execution_is_exposed():
    payload = _get().json()

    controls = payload["capabilities"]

    assert controls["view_capability_inventory"] is True
    assert controls["view_readiness"] is True

    assert controls["run_analytics"] is False
    assert controls["run_experiments"] is False
    assert controls["run_robustness"] is False
    assert controls["mutate_lifecycle"] is False
    assert controls["evaluate_observations"] is False
    assert controls["process_reliability"] is False
    assert controls["process_temporal_quality"] is False
    assert controls["process_system_safety"] is False
    assert controls["restore_research_state"] is False


def test_execution_boundary_remains_prohibited():
    payload = _get().json()

    boundary = payload["execution_boundary"]

    assert boundary["status"] == "PROHIBITED"
    assert boundary["provider"] == "ProhibitedExecutionProvider"
    assert boundary["financial_execution"] is False
    assert boundary["broker_connectivity"] is False
    assert boundary["account_connectivity"] is False


def test_runtime_identity_is_authoritative():
    payload = _get().json()

    runtime = payload["runtime"]

    assert runtime["state"] == "RUNNING"
    assert runtime["environment"] == "RESEARCH"
    assert runtime["version"] == "0.27.0"


def test_configuration_identity_is_preserved():
    payload = _get().json()

    configuration = payload["configuration"]

    assert (
        configuration["snapshot_id"]
        == "CONFIG-BFDCEF6EE22E1395"
    )

    assert (
        configuration["configuration_hash"]
        == "4461634b894399a44c1a3edf33f82d49bb8ba9034f19332ef2f85d7c590ea507"
    )


def test_mutation_methods_are_rejected():
    with TestClient(app) as client:
        for method in (
            client.post,
            client.put,
            client.patch,
            client.delete,
        ):
            response = method(ENDPOINT)

            assert response.status_code in {
                404,
                405,
            }


def test_response_contains_no_sensitive_state():
    response = _get()

    text = response.text.lower()

    for fragment in FORBIDDEN_FRAGMENTS:
        assert fragment not in text


def test_response_contains_no_manufactured_performance_results():
    payload = _get().json()

    forbidden_result_keys = {
        "profit",
        "roi",
        "win_rate",
        "expectancy",
        "performance_score",
        "validation_score",
        "experiment_result",
        "robustness_score",
    }

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                assert (
                    str(key).lower()
                    not in forbidden_result_keys
                )
                walk(child)

        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
