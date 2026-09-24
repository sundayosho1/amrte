from fastapi.testclient import TestClient

from amrte.web.app import create_app


def test_research_portfolio_endpoint_is_versioned_read_only_and_truthful():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get("/api/v1/research-portfolio").json()

        assert payload["candidate_risk_schema_version"] == "1.0"
        assert payload["correlation_schema_version"] == "1.0"
        assert payload["portfolio_snapshot_schema_version"] == "1.0"
        assert payload["runtime_version"] == "1.0"
        assert payload["mode"] == "READ_ONLY"
        assert payload["research_only"] is True
        assert payload["runtime_authority"]["risk_portfolio_authority"] == "ResearchPortfolioRuntime"
        assert payload["runtime_authority"]["p43_assessment_required"] is True
        assert payload["runtime_authority"]["strategy_re_evaluation_available"] is False
        assert payload["runtime_authority"]["candidate_rescoring_available"] is False
        assert payload["runtime_authority"]["arbitration_recompute_available"] is False
        assert payload["composition"]["components"]["research_risk"]["active"] is True
        assert payload["composition"]["components"]["portfolio_context"]["active"] is True
        assert payload["composition"]["components"]["correlation_analysis"]["active"] is True
        assert payload["composition"]["components"]["concentration_analysis"]["active"] is True
        assert payload["composition"]["components"]["portfolio_restrictions"]["active"] is True
        assert payload["composition"]["components"]["portfolio_research_snapshot"]["active"] is True
        assert payload["composition"]["research_pipeline"]["active"] is False
        assert payload["downstream_boundaries"]["final_decision_active"] is False
        assert payload["downstream_boundaries"]["financial_execution_active"] is False
        assert payload["downstream_boundaries"]["capital_allocation_active"] is False
        assert payload["semantic_boundaries"]["research_risk_acceptable_is_authorization"] is False
        assert payload["semantic_boundaries"]["portfolio_compatible_is_capital_allocation"] is False
        assert payload["semantic_boundaries"]["research_weight_is_position_size"] is False
        assert payload["semantic_boundaries"]["portfolio_capacity_is_broker_buying_power"] is False
        assert payload["execution_boundary"]["financial_execution"] == "NONE"

        current = payload["current_state"]
        assert current["risk_policy"]["policy_id"] == "P44_RESEARCH_RISK_POLICY"
        assert current["portfolio_policy"]["policy_id"] == "P44_PORTFOLIO_RESEARCH_POLICY"
        assert current["correlation_policy"]["policy_id"] == "P44_CORRELATION_RESEARCH_POLICY"
        assert current["financial_execution"] == "NONE"

        for method in (client.post, client.put, client.patch, client.delete):
            assert method("/api/v1/research-portfolio").status_code == 405
