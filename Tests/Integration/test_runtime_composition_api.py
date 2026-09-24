from fastapi.testclient import TestClient

from amrte.web.app import create_app


def test_runtime_composition_endpoint_is_read_only():
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/api/v1/runtime-composition")

        assert response.status_code == 200
        payload = response.json()

        assert payload["mode"] == "READ_ONLY"
        assert payload["research_only"] is True
        assert payload["composition_available"] is True
        assert payload["registry_frozen"] is True
        assert payload["validated"] is True

        for method in (
            client.post,
            client.put,
            client.patch,
            client.delete,
        ):
            assert method("/api/v1/runtime-composition").status_code == 405


def test_runtime_composition_inventory_exposes_core_components():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get("/api/v1/runtime-composition").json()

    components = {
        item["component_id"]: item
        for item in payload["components"]
    }

    expected = {
        "audit",
        "clock",
        "composition",
        "configuration",
        "data_trust",
        "execution",
        "health",
        "market_data_configured_dataset",
        "market_data_contract",
        "market_data_source_adapter_framework",
        "market_dataset_authority",
        "market_event_context",
        "market_features",
        "market_intelligence",
        "market_regime",
        "market_session",
        "market_structure",
        "observation_quality",
        "observability",
        "random",
        "research_reliability",
        "research_candidate_runtime",
        "central_scoring",
        "candidate_comparison",
        "strategy_arbitration",
        "post_scoring_research_assessment",
        "research_risk",
        "portfolio_context",
        "correlation_analysis",
        "concentration_analysis",
        "portfolio_restrictions",
        "portfolio_research_snapshot",
        "state",
        "research_pipeline",
        "strategy_evaluation",
        "strategy_registry",
        "temporal_quality",
    }

    assert set(components) == expected
    assert components["execution"]["required"] is True
    assert components["execution"]["active"] is True
    assert components["market_data_contract"]["required"] is True
    assert components["market_data_contract"]["active"] is True
    assert components["market_dataset_authority"]["active"] is True
    assert components["market_data_configured_dataset"]["status"] == "UNAVAILABLE"
    assert components["observation_quality"]["active"] is True
    assert components["research_reliability"]["active"] is True
    assert components["temporal_quality"]["active"] is True
    assert components["data_trust"]["active"] is True
    assert components["market_structure"]["active"] is True
    assert components["market_features"]["active"] is True
    assert components["market_session"]["active"] is True
    assert components["market_event_context"]["active"] is True
    assert components["market_regime"]["active"] is True
    assert components["market_intelligence"]["active"] is True
    assert components["strategy_registry"]["active"] is True
    assert components["strategy_evaluation"]["active"] is True
    assert components["research_candidate_runtime"]["active"] is True
    assert components["central_scoring"]["active"] is True
    assert components["candidate_comparison"]["active"] is True
    assert components["strategy_arbitration"]["active"] is True
    assert components["post_scoring_research_assessment"]["active"] is True
    assert components["research_risk"]["active"] is True
    assert components["portfolio_context"]["active"] is True
    assert components["correlation_analysis"]["active"] is True
    assert components["concentration_analysis"]["active"] is True
    assert components["portfolio_restrictions"]["active"] is True
    assert components["portfolio_research_snapshot"]["active"] is True
    assert components["data_trust"]["persistence_participant"] is True
    assert components["data_trust"]["recovery_participant"] is True
    assert components["market_intelligence"]["persistence_participant"] is True
    assert components["market_intelligence"]["recovery_participant"] is True
    assert components["strategy_evaluation"]["persistence_participant"] is True
    assert components["research_candidate_runtime"]["recovery_participant"] is True
    assert components["central_scoring"]["persistence_participant"] is True
    assert components["post_scoring_research_assessment"]["recovery_participant"] is True
    assert components["research_risk"]["persistence_participant"] is True
    assert components["portfolio_research_snapshot"]["recovery_participant"] is True
    assert components["state"]["persistence_participant"] is True
    assert components["state"]["recovery_participant"] is True


def test_runtime_composition_dependency_and_order_diagnostics_are_deterministic():
    app = create_app()

    with TestClient(app) as client:
        first = client.get("/api/v1/runtime-composition").json()
        second = client.get("/api/v1/runtime-composition").json()

    assert first["initialization_order"] == second["initialization_order"]
    assert first["shutdown_order"] == second["shutdown_order"]
    assert first["shutdown_order"] == list(
        reversed(first["initialization_order"])
    )
    assert "clock" in first["initialization_order"]
    assert (
        first["initialization_order"].index("clock")
        < first["initialization_order"].index("configuration")
    )


def test_runtime_composition_reports_research_pipeline_not_active():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get("/api/v1/runtime-composition").json()

    pipeline = payload["research_pipeline"]

    assert pipeline["registered"] is True
    assert pipeline["active"] is False
    assert pipeline["status"] == "UNAVAILABLE"
    assert pipeline["ready"] is False


def test_system_health_distinguishes_core_component_and_pipeline_state():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get("/api/v1/system/health").json()

    assert payload["status"] == "HEALTHY"
    assert payload["core_runtime_state"] == "RUNNING"
    assert payload["component_readiness"]["ready"] is True
    assert payload["component_health"]["ready"] is True
    assert payload["research_pipeline"]["active"] is False
    assert payload["research_pipeline"]["status"] == "UNAVAILABLE"


def test_health_diagnostics_includes_composition_summary():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get("/api/v1/health-diagnostics").json()

    composition = payload["composition"]

    assert composition["available"] is True
    assert composition["readiness"]["ready"] is True
    assert composition["component_count"] >= 9
    assert composition["research_pipeline"]["active"] is False
