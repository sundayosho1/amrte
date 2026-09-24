from fastapi.testclient import TestClient

from amrte.web.app import create_app


def test_research_performance_endpoint_exposes_p48_status_read_only():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get("/api/v1/research-performance").json()

        assert payload["mode"] == "READ_ONLY"
        assert payload["research_only"] is True
        assert payload["authority"]["historical_decision_source"] == "P47 ResearchDecisionEvidenceRecord"
        assert payload["authority"]["future_observation_source"] == "P39 CanonicalMarketObservation + P40 TrustedResearchObservation"
        assert payload["authority"]["strategy_promotion_available"] is False
        assert payload["authority"]["financial_authorization"] == "NONE"
        assert payload["runtime_version"] == "1.0"
        assert payload["sample_sufficiency"] == "INSUFFICIENT_EVIDENCE"
        assert payload["financial_execution"] == "NONE"
        assert payload["components"]["outcome_window_manager"]["active"] is True
        assert payload["components"]["research_outcome_attribution"]["active"] is True
        assert payload["components"]["research_performance_snapshot"]["active"] is True

        outcomes = client.get("/api/v1/research-outcomes?limit=1000").json()
        assert outcomes["mode"] == "READ_ONLY"
        assert outcomes["available"] is True
        assert outcomes["limit"] == 100
        assert outcomes["items"] == []

        for method in (client.post, client.put, client.patch, client.delete):
            assert method("/api/v1/research-performance").status_code == 405
            assert method("/api/v1/research-outcomes").status_code == 405
