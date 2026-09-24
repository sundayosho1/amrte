from fastapi.testclient import TestClient

from amrte.web.app import create_app


def test_research_improvements_endpoint_exposes_p49_status_read_only():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get("/api/v1/research-improvements?limit=1000").json()

        assert payload["mode"] == "READ_ONLY"
        assert payload["research_only"] is True
        assert payload["runtime_version"] == "1.0"
        assert payload["authority"]["input_boundary"] == "P47 evidence + P48 attribution/snapshot"
        assert payload["authority"]["automatic_change"] is False
        assert payload["authority"]["validation_required"] is True
        assert payload["authority"]["configuration_mutation_available"] is False
        assert payload["authority"]["strategy_mutation_available"] is False
        assert payload["authority"]["financial_authorization"] == "NONE"
        assert payload["limit"] == 100
        assert payload["items"] == []
        assert payload["financial_execution"] == "NONE"
        assert payload["components"]["improvement_evidence_validator"]["active"] is True
        assert payload["components"]["research_improvement_snapshot"]["active"] is True

        detail = client.get("/api/v1/research-improvements/does-not-exist").json()
        assert detail["mode"] == "READ_ONLY"
        assert detail["available"] is False
        assert detail["reason"] == "P49_CANDIDATE_NOT_FOUND"

        for method in (client.post, client.put, client.patch, client.delete):
            assert method("/api/v1/research-improvements").status_code == 405
            assert method("/api/v1/research-improvements/does-not-exist").status_code == 405
