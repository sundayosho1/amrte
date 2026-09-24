from fastapi.testclient import TestClient

from amrte.web.app import create_app


def test_strategy_evaluation_endpoint_is_versioned_read_only_and_truthful():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get("/api/v1/strategy-evaluation").json()

        assert payload["candidate_schema_version"] == "1.0"
        assert payload["evaluation_schema_version"] == "1.0"
        assert payload["runtime_version"] == "1.0"
        assert payload["mode"] == "READ_ONLY"
        assert payload["research_only"] is True
        assert payload["runtime_authority"]["strategy_authority"] == "StrategyEvaluationRuntime"
        assert payload["runtime_authority"]["p41_input_required"] is True
        assert payload["runtime_authority"]["raw_observation_bypass_available"] is False
        assert payload["runtime_authority"]["trusted_observation_bypass_available"] is False
        assert payload["composition"]["components"]["strategy_registry"]["active"] is True
        assert payload["composition"]["components"]["strategy_evaluation"]["active"] is True
        assert payload["composition"]["components"]["research_candidate_runtime"]["active"] is True
        assert payload["composition"]["research_pipeline"]["active"] is False
        assert payload["downstream_boundaries"]["central_scoring_active"] is False
        assert payload["downstream_boundaries"]["strategy_arbitration_active"] is False
        assert payload["downstream_boundaries"]["final_decision_active"] is False
        assert payload["execution_boundary"]["financial_execution"] == "NONE"

        registry = payload["current_state"]["registry"]
        assert {item["strategy_id"] for item in registry} == {
            "S1_TREND_PULLBACK",
            "S2_BREAKOUT_VOLATILITY_EXPANSION_IMMEDIATE",
            "S2_BREAKOUT_VOLATILITY_EXPANSION_RETEST",
            "S3_RANGE_MEAN_REVERSION",
        }

        for method in (client.post, client.put, client.patch, client.delete):
            assert method("/api/v1/strategy-evaluation").status_code == 405
