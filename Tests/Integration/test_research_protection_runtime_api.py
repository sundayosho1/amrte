from fastapi.testclient import TestClient

from amrte.web.app import create_app


def test_research_protection_endpoint_is_versioned_read_only_and_truthful():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get("/api/v1/research-protection").json()

        assert payload["protection_snapshot_schema_version"] == "1.0"
        assert payload["protection_evidence_schema_version"] == "1.0"
        assert payload["runtime_version"] == "1.0"
        assert payload["mode"] == "READ_ONLY"
        assert payload["research_only"] is True
        assert payload["runtime_authority"]["protection_authority"] == "ResearchProtectionRuntime"
        assert payload["runtime_authority"]["p44_snapshot_required"] is True
        assert payload["runtime_authority"]["p44_recomputed"] is False
        assert payload["runtime_authority"]["p43_recomputed"] is False
        assert payload["runtime_authority"]["strategy_re_evaluation_available"] is False
        assert payload["runtime_authority"]["candidate_rescoring_available"] is False
        assert payload["runtime_authority"]["portfolio_risk_recompute_available"] is False
        assert payload["runtime_authority"]["manual_force_allow_available"] is False
        assert payload["runtime_authority"]["safety_bypass_available"] is False
        assert payload["permission_model"]["states"] == ["ALLOWED", "RESTRICTED", "BLOCKED"]
        assert payload["permission_model"]["monotonic"] is True
        assert payload["permission_model"]["blocked_dominates"] is True
        assert payload["permission_model"]["allowed_is_financial_authorization"] is False
        assert payload["composition"]["components"]["protection_input_monitor"]["active"] is True
        assert payload["composition"]["components"]["strategy_health_protection"]["active"] is True
        assert payload["composition"]["components"]["temporal_safety_protection"]["active"] is True
        assert payload["composition"]["components"]["lifecycle_protection"]["active"] is True
        assert payload["composition"]["components"]["dependency_protection"]["active"] is True
        assert payload["composition"]["components"]["system_safety_protection"]["active"] is True
        assert payload["composition"]["components"]["research_protection"]["active"] is True
        assert payload["composition"]["components"]["research_protection_snapshot"]["active"] is True
        assert payload["composition"]["research_pipeline"]["active"] is False
        assert payload["execution_boundary"]["financial_execution"] == "NONE"

        current = payload["current_state"]
        assert current["policy"]["policy_id"] == "P45_RESEARCH_PROTECTION_POLICY"
        assert current["policy"]["fail_closed"] is True
        assert current["financial_execution"] == "NONE"

        for method in (client.post, client.put, client.patch, client.delete):
            assert method("/api/v1/research-protection").status_code == 405
