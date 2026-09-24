from fastapi.testclient import TestClient

from amrte.web.app import create_app


def test_research_evidence_endpoint_exposes_p47_ledger_status_read_only():
    app = create_app()

    with TestClient(app) as client:
        payload = client.get("/api/v1/research-evidence").json()

        assert payload["mode"] == "READ_ONLY"
        assert payload["research_only"] is True
        ledger = payload["ledger"]
        assert ledger["runtime_version"] == "1.0"
        assert ledger["append_only"] is True
        assert ledger["checkpoint_is_ledger"] is False
        assert ledger["historical_evidence_mutation_available"] is False
        assert ledger["financial_execution"] == "NONE"
        assert ledger["components"]["evidence_validation"]["active"] is True
        assert ledger["components"]["evidence_serialization"]["active"] is True
        assert ledger["components"]["research_evidence_ledger"]["active"] is True
        assert ledger["components"]["ledger_integrity_verification"]["active"] is True
        assert ledger["components"]["evidence_reconstruction"]["active"] is True
        assert ledger["status"]["ledger_record_count"] >= 0
        assert ledger["status"]["ledger_head"]
        assert ledger["status"]["integrity_status"] == "VERIFIED"

        detail = client.get("/api/v1/research-evidence/does-not-exist").json()
        assert detail["mode"] == "READ_ONLY"
        assert detail["available"] is False
        assert detail["reason"] == "P47_EVIDENCE_RECORD_NOT_FOUND"

        for method in (client.post, client.put, client.patch, client.delete):
            assert method("/api/v1/research-evidence").status_code == 405
            assert method("/api/v1/research-evidence/does-not-exist").status_code == 405
