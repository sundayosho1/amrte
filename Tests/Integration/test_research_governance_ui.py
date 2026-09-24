from pathlib import Path

from fastapi.testclient import TestClient

from amrte.web.app import create_app


STATIC_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "amrte"
    / "web"
    / "static"
)

PAGE = STATIC_ROOT / "research-governance.html"
SCRIPT = STATIC_ROOT / "research-governance.js"


def client() -> TestClient:
    return TestClient(create_app())


def test_research_governance_page_is_reachable():
    with client() as test_client:
        response = test_client.get(
            "/research-governance"
        )

    assert response.status_code == 200
    assert "text/html" in response.headers[
        "content-type"
    ]

    html = response.text

    assert (
        "Research Governance &amp; Safety"
        in html
    )
    assert "READ-ONLY" in html
    assert "RESEARCH-ONLY" in html


def test_research_governance_static_assets_exist():
    assert PAGE.is_file()
    assert SCRIPT.is_file()

    html = PAGE.read_text(
        encoding="utf-8"
    )

    assert (
        '/static/console.css'
        in html
    )
    assert (
        '/static/research-governance.js'
        in html
    )


def test_research_governance_uses_canonical_shell():
    html = PAGE.read_text(
        encoding="utf-8"
    )

    required = (
        'class="shell"',
        'class="sidebar"',
        'class="nav',
        'href="/"',
        'href="/configuration"',
        'href="/research-controls"',
        'href="/dataset-replay"',
        'href="/observability"',
        'href="/persistence-recovery"',
        'href="/health-diagnostics"',
        'href="/administration"',
        'href="/research-evidence"',
        'href="/research-governance"',
    )

    for fragment in required:
        assert fragment in html


def test_research_governance_contains_required_sections():
    html = PAGE.read_text(
        encoding="utf-8"
    )

    required = (
        "Research Governance &amp; Safety",
        "Runtime Authority",
        "Governance Capability",
        "Lifecycle Governance",
        "System Safety",
        "Observation Quality",
        "Research Reliability",
        "Temporal Quality",
        "Promotion Governance",
        "Recovery Governance",
        "Configuration Safeguards",
        "Execution Boundary",
    )

    for text in required:
        assert text in html


def test_research_governance_declares_capability_state_distinction():
    html = PAGE.read_text(
        encoding="utf-8"
    )

    required = (
        "IMPLEMENTED",
        "RUNTIME-ACTIVE",
        "CURRENT-STATE-AVAILABLE",
        "AVAILABLE_NOT_ACTIVATED",
    )

    for text in required:
        assert text in html


def test_research_governance_uses_authoritative_get_api():
    javascript = SCRIPT.read_text(
        encoding="utf-8"
    )

    assert (
        '"/api/v1/research-governance"'
        in javascript
        or
        "'/api/v1/research-governance'"
        in javascript
    )

    assert "fetch(" in javascript

    assert (
        'method: "GET"' in javascript
        or
        "method: 'GET'" in javascript
    )

    forbidden_methods = (
        'method: "POST"',
        "method: 'POST'",
        'method: "PUT"',
        "method: 'PUT'",
        'method: "PATCH"',
        "method: 'PATCH'",
        'method: "DELETE"',
        "method: 'DELETE'",
    )

    for fragment in forbidden_methods:
        assert fragment not in javascript


def test_research_governance_has_no_mutating_controls():
    combined = (
        PAGE.read_text(encoding="utf-8")
        + "\n"
        + SCRIPT.read_text(encoding="utf-8")
    ).lower()

    forbidden = (
        "activate governance",
        "activate safety",
        "run safety",
        "run governance",
        "process signal",
        "transition lifecycle",
        "promote stage",
        "automatic promotion",
        "request recovery",
        "confirm probation",
        "restore state",
        "delete checkpoint",
        "execute trade",
        "place order",
        "connect broker",
        "connect account",
    )

    for fragment in forbidden:
        assert fragment not in combined


def test_research_governance_does_not_fabricate_current_state():
    combined = (
        PAGE.read_text(encoding="utf-8")
        + "\n"
        + SCRIPT.read_text(encoding="utf-8")
    ).lower()

    forbidden = (
        "current_safety_state",
        "current_lifecycle_state",
        "current_quality_state",
        "current_reliability_state",
        "current_temporal_state",
        "safety score",
        "compliance score",
        "governance score",
    )

    for fragment in forbidden:
        assert fragment not in combined


def test_research_governance_projects_all_governance_capabilities():
    javascript = SCRIPT.read_text(
        encoding="utf-8"
    )

    required = (
        "research_lifecycle",
        "system_safety",
        "observation_quality",
        "research_reliability",
        "temporal_quality_protection",
    )

    for capability in required:
        assert capability in javascript


def test_research_governance_projects_governance_safeguards():
    javascript = SCRIPT.read_text(
        encoding="utf-8"
    )

    required = (
        "promotion_governance",
        "recovery_governance",
        "configuration_safeguards",
        "execution_boundary",
    )

    for field in required:
        assert field in javascript


def test_research_governance_preserves_execution_prohibition():
    combined = (
        PAGE.read_text(encoding="utf-8")
        + "\n"
        + SCRIPT.read_text(encoding="utf-8")
    )

    assert "PROHIBITED" in combined
    assert "Financial execution" in combined


def test_research_governance_navigation_is_enabled_across_console():
    pages = (
        "index.html",
        "configuration.html",
        "research-controls.html",
        "dataset-replay.html",
        "observability.html",
        "persistence-recovery.html",
        "health-diagnostics.html",
        "administration.html",
        "research-evidence.html",
        "research-governance.html",
    )

    for name in pages:
        path = STATIC_ROOT / name
        assert path.is_file()

        html = path.read_text(
            encoding="utf-8"
        )

        assert (
            'href="/research-governance"'
            in html
        )


def test_research_governance_page_has_no_form_submission_surface():
    html = PAGE.read_text(
        encoding="utf-8"
    ).lower()

    assert "<form" not in html
    assert 'type="submit"' not in html
    assert "contenteditable" not in html


def test_research_governance_javascript_has_error_projection():
    javascript = SCRIPT.read_text(
        encoding="utf-8"
    )

    assert (
        "research-governance-error"
        in javascript
    )
    assert "response.ok" in javascript


def test_research_governance_page_explains_non_active_authority():
    html = PAGE.read_text(
        encoding="utf-8"
    )

    assert (
        "IMPLEMENTED"
        in html
    )
    assert (
        "RUNTIME-ACTIVE"
        in html
    )
    assert (
        "CURRENT-STATE-AVAILABLE"
        in html
    )


def test_research_governance_ui_contains_no_financial_execution_surface():
    combined = (
        PAGE.read_text(encoding="utf-8")
        + "\n"
        + SCRIPT.read_text(encoding="utf-8")
    ).lower()

    forbidden = (
        "buy",
        "sell",
        "lot size",
        "leverage",
        "margin",
        "stop loss",
        "take profit",
        "broker login",
        "account login",
        "api key",
        "access token",
        "place trade",
        "open position",
        "close position",
    )

    for fragment in forbidden:
        assert fragment not in combined
