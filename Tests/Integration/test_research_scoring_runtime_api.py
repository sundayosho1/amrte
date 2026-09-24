from fastapi.testclient import TestClient

from amrte.web.app import create_app


def test_research_scoring_endpoint_is_versioned_read_only_and_truthful():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get("/api/v1/research-scoring").json()

        assert payload["scored_candidate_schema_version"] == "1.0"
        assert payload["assessment_schema_version"] == "1.0"
        assert payload["runtime_version"] == "1.0"
        assert payload["mode"] == "READ_ONLY"
        assert payload["research_only"] is True
        assert payload["runtime_authority"]["scoring_authority"] == "ResearchScoringRuntime"
        assert payload["runtime_authority"]["p42_input_required"] is True
        assert payload["runtime_authority"]["strategy_re_evaluation_available"] is False
        assert payload["runtime_authority"]["raw_observation_bypass_available"] is False
        assert payload["runtime_authority"]["trusted_observation_bypass_available"] is False
        assert payload["runtime_authority"]["market_intelligence_bypass_available"] is False
        assert payload["composition"]["components"]["central_scoring"]["active"] is True
        assert payload["composition"]["components"]["candidate_comparison"]["active"] is True
        assert payload["composition"]["components"]["strategy_arbitration"]["active"] is True
        assert payload["composition"]["components"]["post_scoring_research_assessment"]["active"] is True
        assert payload["composition"]["research_pipeline"]["active"] is False
        assert payload["downstream_boundaries"]["risk_decision_active"] is False
        assert payload["downstream_boundaries"]["portfolio_decision_active"] is False
        assert payload["downstream_boundaries"]["final_decision_active"] is False
        assert payload["execution_boundary"]["financial_execution"] == "NONE"

        current = payload["current_state"]
        assert current["scoring_model"]
        assert current["normalization_policy"]["bounds"] == [0.0, 100.0]
        assert current["arbitration_policy"]["version"] == "1.0"
        assert current["financial_authorization"] == "NONE"

        for method in (client.post, client.put, client.patch, client.delete):
            assert method("/api/v1/research-scoring").status_code == 405
