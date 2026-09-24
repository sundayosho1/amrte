from __future__ import annotations

from fastapi.testclient import TestClient

from amrte.web.app import create_app


EXPECTED_CAPABILITIES = {
    "system_safety",
    "research_lifecycle",
    "observation_quality",
    "research_reliability",
    "temporal_quality_protection",
}


def _get_payload():
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/api/v1/research-governance")

    return response


def test_research_governance_endpoint_exists():
    response = _get_payload()

    assert response.status_code == 200


def test_research_governance_is_read_only_projection():
    response = _get_payload()
    data = response.json()

    assert data["mode"] == "READ_ONLY"
    assert data["research_only"] is True

    assert data["authority"]["projection_only"] is True
    assert data["authority"]["new_runtime_authority"] is False
    assert data["authority"]["target_engine_instantiation"] is False


def test_runtime_identity_is_authoritative():
    response = _get_payload()
    data = response.json()

    assert data["runtime"]["state"] == "RUNNING"
    assert data["runtime"]["environment"] == "RESEARCH"
    assert data["runtime"]["version"] == "0.27.0"


def test_governance_capability_inventory_is_exact():
    response = _get_payload()
    data = response.json()

    capabilities = data["governance_capabilities"]

    assert {
        item["capability"]
        for item in capabilities
    } == EXPECTED_CAPABILITIES

    assert len(capabilities) == len(EXPECTED_CAPABILITIES)


def test_implemented_does_not_imply_runtime_authority():
    response = _get_payload()
    data = response.json()

    for item in data["governance_capabilities"]:
        assert item["implemented"] is True
        assert item["runtime_authority"] is False
        assert item["runtime_active"] is False
        assert item["current_state_available"] is False
        assert item["status"] == "AVAILABLE_NOT_ACTIVATED"


def test_lifecycle_governance_contract_is_definition_only():
    response = _get_payload()
    data = response.json()

    lifecycle = data["lifecycle_governance"]

    assert lifecycle["implemented"] is True
    assert lifecycle["runtime_authority"] is False
    assert lifecycle["strict_state_machine"] is True
    assert lifecycle["fail_closed"] is True
    assert lifecycle["require_lineage"] is True
    assert lifecycle["require_dataset_match"] is True
    assert lifecycle["require_configuration_match"] is True
    assert lifecycle["require_temporal_integrity"] is True
    assert lifecycle["require_quality_for_authorization"] is True
    assert lifecycle["require_workflow_for_activation"] is True

    assert lifecycle["current_state_available"] is False
    assert "current_state" not in lifecycle


def test_system_safety_contract_is_definition_only():
    response = _get_payload()
    data = response.json()

    safety = data["system_safety"]

    assert safety["implemented"] is True
    assert safety["runtime_authority"] is False
    assert safety["current_state_available"] is False

    assert safety["fail_closed_recovery"] is True
    assert safety["recovery_requires_evidence"] is True
    assert safety["recovery_requires_actor"] is True
    assert safety["recovery_requires_reason"] is True
    assert safety["probation_required"] is True
    assert safety["circuit_breaker_defined"] is True
    assert safety["emergency_stop_defined"] is True

    assert "current_state" not in safety
    assert "current_incident" not in safety


def test_quality_protection_contracts_are_non_active_definitions():
    response = _get_payload()
    data = response.json()

    quality = data["quality_protection"]

    for name in (
        "observation_quality",
        "research_reliability",
        "temporal_quality",
    ):
        item = quality[name]

        assert item["implemented"] is True
        assert item["runtime_authority"] is False
        assert item["runtime_active"] is False
        assert item["current_state_available"] is False
        assert item["non_amplifying"] is True

        assert "current_state" not in item


def test_promotion_governance_requires_sequential_manual_approval():
    response = _get_payload()
    data = response.json()

    promotion = data["promotion_governance"]

    assert promotion["implemented"] is True
    assert promotion["automatic_promotion"] is False
    assert promotion["manual_approval_required"] is True
    assert promotion["stage_skipping_allowed"] is False
    assert promotion["evidence_required"] is True

    assert promotion["final_stage"] == "RESEARCH_OPERATION_APPROVED"


def test_recovery_governance_is_fail_closed():
    response = _get_payload()
    data = response.json()

    recovery = data["recovery_governance"]

    assert recovery["fail_closed"] is True
    assert recovery["silent_repair"] is False
    assert recovery["state_manufacture"] is False
    assert recovery["automatic_recovery"] is False
    assert recovery["evidence_required"] is True


def test_configuration_safeguards_are_exposed_without_mutation():
    response = _get_payload()
    data = response.json()

    safeguards = data["configuration_safeguards"]

    assert safeguards["fail_closed"] is True
    assert safeguards["deterministic_backtest"] is True
    assert safeguards["no_look_ahead"] is True
    assert safeguards["strict_market_data_integrity"] is True
    assert safeguards["adaptive_risk_amplification_allowed"] is False


def test_execution_boundary_remains_prohibited():
    response = _get_payload()
    data = response.json()

    boundary = data["execution_boundary"]

    assert boundary["status"] == "PROHIBITED"
    assert boundary["provider"] == "ProhibitedExecutionProvider"

    assert boundary["financial_execution"] is False
    assert boundary["broker_connectivity"] is False
    assert boundary["account_connectivity"] is False


def test_controls_are_read_only():
    response = _get_payload()
    data = response.json()

    controls = data["controls"]

    assert controls["view_governance_inventory"] is True
    assert controls["view_safety_definitions"] is True
    assert controls["view_promotion_governance"] is True
    assert controls["view_recovery_governance"] is True

    assert controls["initialize"] is False
    assert controls["process"] is False
    assert controls["transition"] is False
    assert controls["evaluate"] is False
    assert controls["promote"] is False
    assert controls["request_recovery"] is False
    assert controls["confirm_probation"] is False
    assert controls["restore"] is False
    assert controls["mutate"] is False


def test_mutation_methods_are_not_exposed():
    app = create_app()

    with TestClient(app) as client:
        for method in ("post", "put", "patch", "delete"):
            response = getattr(
                client,
                method,
            )(
                "/api/v1/research-governance"
            )

            assert response.status_code in (404, 405)


def test_response_does_not_claim_inactive_runtime_states():
    response = _get_payload()
    data = response.json()

    forbidden_keys = {
        "current_safety_state",
        "current_lifecycle_state",
        "current_quality_state",
        "current_reliability_stage",
        "current_temporal_stage",
        "current_incident",
    }

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                assert key not in forbidden_keys
                walk(item)

        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data)


def test_response_contains_no_execution_or_credential_surface():
    response = _get_payload()

    text = response.text.lower()

    forbidden_fragments = (
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

    for fragment in forbidden_fragments:
        assert fragment not in text