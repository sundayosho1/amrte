from fastapi.testclient import TestClient

from amrte.web.app import create_app


def test_research_decisions_endpoint_is_versioned_read_only_and_truthful():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get("/api/v1/research-decisions").json()

        assert payload["processing_context_schema_version"] == "1.0"
        assert payload["final_decision_schema_version"] == "1.0"
        assert payload["trace_schema_version"] == "1.0"
        assert payload["runtime_version"] == "1.0"
        assert payload["mode"] == "READ_ONLY"
        assert payload["research_only"] is True
        assert payload["runtime_authority"]["final_research_decision_authority"] == "MasterResearchDecisionOrchestrator"
        assert payload["runtime_authority"]["p45_snapshot_required"] is True
        assert payload["runtime_authority"]["p39_recomputed"] is False
        assert payload["runtime_authority"]["p40_recomputed"] is False
        assert payload["runtime_authority"]["p41_recomputed"] is False
        assert payload["runtime_authority"]["p42_recomputed"] is False
        assert payload["runtime_authority"]["p43_recomputed"] is False
        assert payload["runtime_authority"]["p44_recomputed"] is False
        assert payload["runtime_authority"]["p45_recomputed"] is False
        assert payload["runtime_authority"]["manual_force_allow_available"] is False
        assert payload["runtime_authority"]["restriction_bypass_available"] is False
        assert payload["decision_model"]["states"] == [
            "NO_ACTION",
            "REJECTED",
            "RESTRICTED",
            "ELIGIBLE_RESEARCH",
            "FAILED",
        ]
        assert payload["decision_model"]["eligible_research_is_trade_authorization"] is False
        assert payload["decision_model"]["final_decision_is_financial_authorization"] is False
        assert payload["decision_model"]["missing_stage_evidence_fails_closed"] is True
        assert payload["decision_model"]["p45_blocked_can_become_positive"] is False
        assert payload["decision_model"]["p45_restricted_can_become_unrestricted"] is False
        assert payload["composition"]["components"]["research_processing_context"]["active"] is True
        assert payload["composition"]["components"]["stage_evidence_verification"]["active"] is True
        assert payload["composition"]["components"]["master_research_decision"]["active"] is True
        assert payload["composition"]["components"]["research_decision_trace"]["active"] is True
        assert payload["composition"]["components"]["research_decision_ledger"]["active"] is True
        assert payload["composition"]["research_pipeline"]["active"] is False
        assert payload["execution_boundary"]["financial_execution"] == "NONE"

        current = payload["current_state"]
        assert current["policy"]["policy_id"] == "P46_MASTER_RESEARCH_DECISION_POLICY"
        assert current["policy"]["fail_closed"] is True
        assert current["financial_execution"] == "NONE"

        for method in (client.post, client.put, client.patch, client.delete):
            assert method("/api/v1/research-decisions").status_code == 405
