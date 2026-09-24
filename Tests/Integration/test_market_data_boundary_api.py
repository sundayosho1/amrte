from fastapi.testclient import TestClient

from amrte.web.app import create_app


def test_market_data_boundary_endpoint_is_read_only_and_explicit():
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/api/v1/market-data-boundary")
        assert response.status_code == 200
        payload = response.json()

        assert payload["mode"] == "READ_ONLY"
        assert payload["research_only"] is True
        assert payload["observation_schema"]["supported_types"] == ["BAR"]
        assert payload["observation_schema"]["temporal_semantics"] == "BAR_CLOSE"
        assert payload["dataset_authority"]["ready"] is True
        assert payload["dataset_authority"]["configured_dataset_loaded"] is False
        assert payload["source_adapter_framework"]["ready"] is True
        assert payload["replay"]["uses_available_at"] is True
        assert payload["execution_boundary"]["execution"] == "PROHIBITED"
        assert payload["execution_boundary"]["financial_execution_available"] is False
        assert payload["composition"]["research_pipeline"]["active"] is False

        for method in (
            client.post,
            client.put,
            client.patch,
            client.delete,
        ):
            assert method("/api/v1/market-data-boundary").status_code == 405


def test_dataset_replay_projection_reports_canonical_boundary_authority():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get("/api/v1/dataset-replay").json()

    boundary = payload["canonical_market_data_boundary"]
    assert boundary["registered"] is True
    assert boundary["components"]["market_data_contract"]["ready"] is True
    assert boundary["components"]["market_dataset_authority"]["ready"] is True
    assert boundary["configured_dataset_loaded"] is False

    capabilities = {
        item["capability"]: item
        for item in payload["implemented_capabilities"]
    }
    assert capabilities["CANONICAL_MARKET_OBSERVATION_CONTRACT"]["runtime_authoritative"] is True
    assert capabilities["SOURCE_ADAPTER_FRAMEWORK"]["runtime_authoritative"] is True
    assert capabilities["CANONICAL_DATASET_MANIFEST"]["runtime_authoritative"] is True
    assert capabilities["POINT_IN_TIME_MARKET_REPLAY"]["runtime_authoritative"] is True
    assert payload["execution_boundary"]["financial_execution_available"] is False
