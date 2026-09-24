from fastapi.testclient import TestClient

from amrte.web.app import create_app


def test_data_quality_runtime_endpoint_is_versioned_read_only_and_truthful():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get("/api/v1/data-quality-runtime").json()

        assert payload["schema_version"] == "1.0"
        assert payload["runtime_version"] == "1.0"
        assert payload["mode"] == "READ_ONLY"
        assert payload["research_only"] is True
        assert payload["runtime_authority"]["ingestion_authority"] == "DataQualityTrustRuntime"
        assert payload["runtime_authority"]["single_ingestion_authority"] is True
        assert payload["trust_model"]["data_received_not_data_trusted"] is True
        assert payload["trust_model"]["future_evidence_rejected"] is True
        assert payload["composition"]["components"]["data_trust"]["active"] is True
        assert payload["composition"]["research_pipeline"]["active"] is False
        assert payload["execution_boundary"]["financial_execution"] == "NONE"

        for method in (client.post, client.put, client.patch, client.delete):
            assert method("/api/v1/data-quality-runtime").status_code == 405


def test_research_lifecycle_quality_projection_reports_prompt40_runtime_authority():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get("/api/v1/research-lifecycle-quality").json()

    assert payload["runtime_authority"]["target_engines_registered"] is True
    assert payload["runtime_authority"]["target_engines_runtime_active"] is True
    assert payload["domains"]["observation_quality"]["runtime_authority"] is True
    assert payload["domains"]["research_reliability"]["runtime_authority"] is True
    assert payload["domains"]["temporal_quality"]["runtime_authority"] is True
    assert payload["domains"]["system_safety"]["runtime_authority"] is True
    assert payload["current_state"]["available"] is True
    assert payload["safety_boundary"]["financial_execution"] is False
