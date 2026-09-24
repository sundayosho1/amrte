from fastapi.testclient import TestClient

from amrte.web.app import create_app


def test_forward_research_api_is_read_only_and_bounded():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get("/api/v1/forward-runtime?limit=1000").json()
        assert payload["mode"] == "READ_ONLY"
        assert payload["research_only"] is True
        assert payload["runtime_version"] == "1.0"
        assert payload["authority"]["input_boundary"] == "P50 VersionedResearchConfiguration + P39 CanonicalMarketObservation"
        assert payload["authority"]["observation_trust_authority"] == "P40 DataQualityTrustRuntime"
        assert payload["authority"]["configuration_mutation"] is False
        assert payload["authority"]["automatic_retuning"] is False
        assert payload["authority"]["financial_authorization"] == "NONE"
        assert payload["limit"] == 100
        assert payload["items"] == []
        assert payload["components"]["forward_research_runtime"]["active"] is True
        assert payload["components"]["forward_runtime_recovery"]["active"] is True

        sessions = client.get("/api/v1/forward-sessions?limit=1000").json()
        assert sessions["mode"] == "READ_ONLY"
        assert sessions["limit"] == 100
        assert sessions["financial_execution"] == "NONE"

        missing = client.get("/api/v1/forward-sessions/does-not-exist").json()
        assert missing["mode"] == "READ_ONLY"
        assert missing["available"] is False
        assert missing["reason"] == "P51_SESSION_NOT_FOUND"

        streams = client.get("/api/v1/forward-streams?limit=1000").json()
        assert streams["mode"] == "READ_ONLY"
        assert streams["limit"] == 100
        assert streams["items"] == []

        shadow = client.get("/api/v1/shadow-research?limit=1000").json()
        assert shadow["mode"] == "READ_ONLY"
        assert shadow["limit"] == 100
        assert shadow["items"] == []

        for path in (
            "/api/v1/forward-runtime",
            "/api/v1/forward-sessions",
            "/api/v1/forward-sessions/does-not-exist",
            "/api/v1/forward-streams",
            "/api/v1/shadow-research",
        ):
            for method in (client.post, client.put, client.patch, client.delete):
                assert method(path).status_code == 405
