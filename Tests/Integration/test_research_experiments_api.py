from fastapi.testclient import TestClient

from amrte.web.app import create_app


def test_research_experiments_api_is_read_only_and_bounded():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get("/api/v1/research-experiments?limit=1000").json()
        assert payload["mode"] == "READ_ONLY"
        assert payload["research_only"] is True
        assert payload["runtime_version"] == "1.0"
        assert payload["authority"]["input_boundary"] == "P49 ImprovementCandidate"
        assert payload["authority"]["automatic_change"] is False
        assert payload["authority"]["financial_authorization"] == "NONE"
        assert payload["limit"] == 100
        assert payload["items"] == []
        assert payload["components"]["experiment_registry"]["active"] is True
        assert payload["components"]["research_experiment_runtime"]["active"] is True
        assert payload["components"]["versioned_research_configuration"]["active"] is True

        detail = client.get("/api/v1/research-experiments/does-not-exist").json()
        assert detail["mode"] == "READ_ONLY"
        assert detail["available"] is False
        assert detail["reason"] == "P50_EXPERIMENT_NOT_FOUND"

        configs = client.get("/api/v1/research-configurations?limit=1000").json()
        assert configs["mode"] == "READ_ONLY"
        assert configs["limit"] == 100
        assert configs["financial_execution"] == "NONE"

        for path in ("/api/v1/research-experiments", "/api/v1/research-experiments/does-not-exist", "/api/v1/research-configurations"):
            for method in (client.post, client.put, client.patch, client.delete):
                assert method(path).status_code == 405
