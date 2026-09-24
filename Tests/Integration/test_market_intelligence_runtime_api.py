from fastapi.testclient import TestClient

from amrte.web.app import create_app


def test_market_intelligence_endpoint_is_versioned_read_only_and_truthful():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get("/api/v1/market-intelligence").json()

        assert payload["schema_version"] == "1.0"
        assert payload["runtime_version"] == "1.0"
        assert payload["mode"] == "READ_ONLY"
        assert payload["research_only"] is True
        assert payload["runtime_authority"]["intelligence_authority"] == "MarketIntelligenceRuntime"
        assert payload["runtime_authority"]["trusted_observation_input_required"] is True
        assert payload["runtime_authority"]["raw_observation_bypass_available"] is False
        assert payload["trusted_boundary"]["accepted_trust_states"] == ["TRUSTED", "TRUSTED_WITH_WARNINGS"]
        assert "REJECTED" in payload["trusted_boundary"]["blocked_trust_states"]
        assert payload["composition"]["components"]["market_intelligence"]["active"] is True
        assert payload["composition"]["research_pipeline"]["active"] is False
        assert payload["execution_boundary"]["financial_execution"] == "NONE"

        for method in (client.post, client.put, client.patch, client.delete):
            assert method("/api/v1/market-intelligence").status_code == 405
