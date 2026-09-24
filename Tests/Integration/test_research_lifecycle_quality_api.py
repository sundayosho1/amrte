from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amrte.web.app import create_app


ENDPOINT = "/api/v1/research-lifecycle-quality"

EXPECTED_DOMAINS = {
    "research_lifecycle",
    "observation_quality",
    "research_reliability",
    "temporal_quality",
    "system_safety",
}

ALLOWED_IMPLEMENTATION_STATES = {
    "IMPLEMENTED",
    "UNAVAILABLE",
    "NOT_VERIFIED",
}


@pytest.fixture()
def client():
    app = create_app()

    with TestClient(app) as test_client:
        yield test_client


def get_payload(client):
    response = client.get(ENDPOINT)
    assert response.status_code == 200
    return response.json()


def test_research_lifecycle_quality_endpoint_exists(client):
    response = client.get(ENDPOINT)

    assert response.status_code == 200


def test_product_identity_and_read_only_boundary(client):
    payload = get_payload(client)

    assert payload["product"] == (
        "Research Lifecycle & Quality Assurance Console"
    )
    assert payload["environment"] == "RESEARCH"
    assert payload["read_only"] is True


def test_exact_domain_inventory(client):
    payload = get_payload(client)

    domains = payload["domains"]

    assert set(domains) == EXPECTED_DOMAINS
    assert len(domains) == 5


def test_all_domains_are_implementation_evidence_not_runtime_state(client):
    payload = get_payload(client)

    active_domains = {
        "observation_quality",
        "research_reliability",
        "temporal_quality",
        "system_safety",
    }
    for name in EXPECTED_DOMAINS:
        domain = payload["domains"][name]

        assert domain["implementation_state"] in (
            ALLOWED_IMPLEMENTATION_STATES
        )

        assert domain["implemented"] is True
        assert domain["runtime_active"] is (name in active_domains)
        assert domain["runtime_authority"] is (name in active_domains)
        assert domain["current_state_available"] is (name in active_domains)


def test_engine_authority_names_are_exact(client):
    payload = get_payload(client)

    assert (
        payload["domains"]["research_lifecycle"]["engine"]
        == "ResearchLifecycleEngine"
    )

    assert (
        payload["domains"]["observation_quality"]["engine"]
        == "ObservationQualityEngine"
    )

    assert (
        payload["domains"]["research_reliability"]["engine"]
        == "ResearchReliabilityEngine"
    )

    assert (
        payload["domains"]["temporal_quality"]["engine"]
        == "TemporalQualityProtectionEngine"
    )

    assert (
        payload["domains"]["system_safety"]["engine"]
        == "SystemSafetyEngine"
    )


def test_engine_versions_are_static_implementation_evidence(client):
    payload = get_payload(client)

    for name in EXPECTED_DOMAINS:
        domain = payload["domains"][name]

        assert domain["engine_version"] == "1.0"
        assert domain["recovery_schema_version"] == "1.0"


def test_lifecycle_state_model(client):
    payload = get_payload(client)

    domain = payload["domains"]["research_lifecycle"]

    assert domain["states"] == [
        "PROPOSED",
        "VALIDATED",
        "AUTHORIZED",
        "QUEUED",
        "ACTIVATED",
        "ACTIVE",
        "SAFEGUARDED",
        "MONITORED",
        "RESOLVED",
        "ARCHIVED",
        "REJECTED",
        "CANCELLED",
        "EXPIRED",
        "INVALIDATED",
        "FAILED",
    ]

    assert domain["health_states"] == [
        "HEALTHY",
        "DEGRADED",
        "QUARANTINED",
        "INVALID",
        "UNKNOWN",
    ]

    assert domain["decisions"] == [
        "ALLOW",
        "BLOCK",
        "NO_ACTION",
        "INVALID",
    ]


def test_observation_quality_state_model(client):
    payload = get_payload(client)

    domain = payload["domains"]["observation_quality"]

    assert domain["observation_health"] == [
        "HEALTHY",
        "DEGRADED",
        "STALE",
        "INVALID",
        "UNAVAILABLE",
        "UNKNOWN",
    ]

    assert domain["quality_states"] == [
        "HEALTHY",
        "DEGRADED",
        "POOR",
        "UNTRUSTED",
        "UNAVAILABLE",
        "UNKNOWN",
    ]

    assert domain["restrictions"] == [
        "ALLOW",
        "RESTRICT",
        "BLOCK",
        "NO_ACTION",
    ]

    assert domain["deviation_regimes"] == [
        "NORMAL",
        "ELEVATED",
        "HIGH",
        "EXTREME",
        "UNKNOWN",
    ]


def test_reliability_state_model(client):
    payload = get_payload(client)

    domain = payload["domains"]["research_reliability"]

    assert domain["stages"] == [
        "NORMAL",
        "WATCH",
        "RESTRICTED",
        "PROTECTED",
        "SUSPENDED",
        "UNKNOWN",
    ]

    assert domain["health_states"] == [
        "HEALTHY",
        "DEGRADED",
        "RESTRICTED",
        "INVALID",
        "UNKNOWN",
    ]

    assert domain["decisions"] == [
        "ACCEPTED",
        "NO_ACTION",
        "BLOCKED",
        "INVALID",
    ]


def test_temporal_quality_state_model(client):
    payload = get_payload(client)

    domain = payload["domains"]["temporal_quality"]

    assert domain["stages"] == [
        "NORMAL",
        "WATCH",
        "RESTRICTED",
        "COOLDOWN",
        "SUSPENDED",
        "UNKNOWN",
    ]

    assert domain["outcome_classes"] == [
        "ADVERSE",
        "NEUTRAL",
        "FAVORABLE",
        "UNKNOWN",
    ]

    assert domain["cooldown_states"] == [
        "INACTIVE",
        "ACTIVE",
        "EXPIRED_PENDING_CONFIRMATION",
        "RELEASED",
    ]

    assert domain["decisions"] == [
        "ACCEPTED",
        "NO_ACTION",
        "BLOCKED",
        "INVALID",
    ]


def test_system_safety_state_model(client):
    payload = get_payload(client)

    domain = payload["domains"]["system_safety"]

    assert domain["states"] == [
        "NORMAL",
        "CAUTION",
        "RESTRICTED",
        "CIRCUIT_OPEN",
        "EMERGENCY_STOP",
        "RECOVERY_PENDING",
        "PROBATION",
        "UNKNOWN",
    ]

    assert domain["signal_severities"] == [
        "INFO",
        "LOW",
        "MEDIUM",
        "HIGH",
        "CRITICAL",
        "UNKNOWN",
    ]

    assert domain["incident_states"] == [
        "OPEN",
        "LATCHED",
        "RECOVERY_PENDING",
        "PROBATION",
        "RESOLVED",
    ]

    assert domain["trigger_scopes"] == [
        "SCOPED",
        "GLOBAL",
    ]

    assert domain["decisions"] == [
        "ACCEPTED",
        "NO_ACTION",
        "BLOCKED",
        "INVALID",
    ]


def test_runtime_authority_classification(client):
    payload = get_payload(client)

    authority = payload["runtime_authority"]

    assert authority["target_engines_registered"] is True
    assert authority["target_engines_runtime_active"] is True
    assert authority["target_engines_current_state_available"] is True

    assert authority["authoritative_runtime"] == (
        "PersistentResearchRuntime"
    )


def test_current_state_is_explicitly_unavailable(client):
    payload = get_payload(client)

    availability = payload["current_state"]

    assert availability["available"] is True
    assert availability["status"] == "AVAILABLE"

    assert "runtime" in availability["reason"].lower()


def test_research_only_safety_boundary(client):
    payload = get_payload(client)

    boundary = payload["safety_boundary"]

    assert boundary["environment"] == "RESEARCH"
    assert boundary["financial_execution"] is False
    assert boundary["broker_connectivity"] is False
    assert boundary["account_connectivity"] is False
    assert boundary["order_execution"] is False
    assert boundary["position_management"] is False
    assert boundary["live_execution"] is False
    assert boundary["demo_execution"] is False


def test_console_does_not_claim_engine_runtime_state(client):
    payload = get_payload(client)

    serialized = str(payload).lower()

    forbidden_claims = (
        "currently healthy",
        "currently degraded",
        "currently restricted",
        "currently active",
        "current lifecycle state",
        "active safety state",
    )

    for claim in forbidden_claims:
        assert claim not in serialized


@pytest.mark.parametrize(
    "method",
    ["post", "put", "patch", "delete"],
)
def test_mutating_http_methods_are_not_allowed(client, method):
    response = getattr(client, method)(ENDPOINT)

    assert response.status_code == 405


def test_no_process_or_engine_control_surface(client):
    payload = get_payload(client)

    serialized = str(payload).lower()

    forbidden = (
        "start_engine",
        "stop_engine",
        "transition_engine",
        "evaluate_engine",
        "process_engine",
        "restore_engine",
        "recover_engine",
        "request_recovery",
        "confirm_probation",
        "confirm_cooldown_release",
        "shutdown_runtime",
        "restart_runtime",
    )

    for identifier in forbidden:
        assert identifier not in serialized
