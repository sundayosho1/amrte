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
        "execution",
        "health",
        "observability",
        "random",
        "state",
        "research_pipeline",
    }

    assert set(components) == expected
    assert components["execution"]["required"] is True
    assert components["execution"]["active"] is True
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
