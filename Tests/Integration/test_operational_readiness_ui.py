from pathlib import Path

from fastapi.testclient import TestClient

from amrte.web.app import app


STATIC_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "amrte"
    / "web"
    / "static"
)

HTML_PATH = (
    STATIC_ROOT
    / "operational-readiness.html"
)

JS_PATH = (
    STATIC_ROOT
    / "operational-readiness.js"
)


def test_operational_readiness_page_is_reachable():
    with TestClient(app) as client:
        response = client.get(
            "/operational-readiness"
        )

    assert response.status_code == 200
    assert (
        "Operational Readiness"
        in response.text
    )


def test_operational_readiness_html_exists():
    assert HTML_PATH.exists()


def test_operational_readiness_javascript_exists():
    assert JS_PATH.exists()


def test_operational_readiness_html_uses_shared_console_shell():
    html = HTML_PATH.read_text(
        encoding="utf-8"
    )

    assert "/static/console.css" in html
    assert (
        "/static/operational-readiness.js"
        in html
    )

    assert "Operational Readiness" in html
    assert "Evidence" in html


def test_operational_readiness_ui_exposes_required_evidence_domains():
    html = HTML_PATH.read_text(
        encoding="utf-8"
    )

    required_markers = (
        "runtime-lifecycle",
        "persistence-recovery",
        "observability-readiness",
        "health-diagnostics",
        "windows-host",
        "research-safety",
    )

    for marker in required_markers:
        assert marker in html


def test_operational_readiness_ui_distinguishes_evidence_states():
    html = HTML_PATH.read_text(
        encoding="utf-8"
    )

    assert "evidence-state" in html
    assert "limitations" in html


def test_operational_readiness_javascript_uses_qualified_api():
    javascript = JS_PATH.read_text(
        encoding="utf-8"
    )

    assert (
        "/api/v1/operational-readiness"
        in javascript
    )


def test_operational_readiness_javascript_does_not_expose_process_controls():
    javascript = JS_PATH.read_text(
        encoding="utf-8"
    ).lower()

    forbidden = (
        "start-runtime",
        "stop-runtime",
        "restart-runtime",
        "kill-process",
        "terminate-process",
        "resume-runtime",
        "shutdown-runtime",
        "checkpoint-runtime",
        "restore-runtime",
        "recover-runtime",
    )

    for token in forbidden:
        assert token not in javascript


def test_operational_readiness_html_does_not_expose_process_controls():
    html = HTML_PATH.read_text(
        encoding="utf-8"
    ).lower()

    forbidden = (
        "start runtime",
        "stop runtime",
        "restart runtime",
        "kill process",
        "terminate process",
        "resume runtime",
        "shutdown runtime",
        "create checkpoint",
        "restore checkpoint",
        "run recovery",
    )

    for token in forbidden:
        assert token not in html


def test_operational_readiness_ui_preserves_research_only_language():
    html = HTML_PATH.read_text(
        encoding="utf-8"
    ).lower()

    required = (
        "research",
        "read-only",
    )

    for token in required:
        assert token in html


def test_operational_readiness_javascript_has_no_mutating_http_methods():
    javascript = JS_PATH.read_text(
        encoding="utf-8"
    ).upper()

    forbidden = (
        'METHOD: "POST"',
        "METHOD: 'POST'",
        'METHOD: "PUT"',
        "METHOD: 'PUT'",
        'METHOD: "PATCH"',
        "METHOD: 'PATCH'",
        'METHOD: "DELETE"',
        "METHOD: 'DELETE'",
    )

    for token in forbidden:
        assert token not in javascript


def test_operational_readiness_ui_does_not_claim_native_windows_qualification():
    html = HTML_PATH.read_text(
        encoding="utf-8"
    ).lower()

    prohibited_claims = (
        "native windows qualified",
        "windows service qualified",
        "production ready",
        "fully qualified for windows",
    )

    for claim in prohibited_claims:
        assert claim not in html


def test_operational_readiness_ui_does_not_claim_deployment_engine_is_active():
    html = HTML_PATH.read_text(
        encoding="utf-8"
    ).lower()

    prohibited_claims = (
        "deploymentdiagnosticsengine active",
        "deployment diagnostics active",
        "deployment diagnostics runtime authority",
    )

    for claim in prohibited_claims:
        assert claim not in html
