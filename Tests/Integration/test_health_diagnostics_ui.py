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


def test_health_diagnostics_page_is_reachable():
    app = create_app()

    with TestClient(app) as client:
        response = client.get(
            "/health-diagnostics"
        )

        assert response.status_code == 200

        body = response.text

        assert "Health &amp; Diagnostics" in body
        assert "READ-ONLY" in body
        assert "RESEARCH-ONLY" in body


def test_health_diagnostics_static_assets_exist():
    html = (
        STATIC_ROOT
        / "health-diagnostics.html"
    )

    javascript = (
        STATIC_ROOT
        / "health-diagnostics.js"
    )

    assert html.is_file()
    assert javascript.is_file()

    assert (
        javascript.name
        in html.read_text(
            encoding="utf-8"
        )
    )


def test_health_diagnostics_ui_contains_required_sections():
    html = (
        STATIC_ROOT
        / "health-diagnostics.html"
    ).read_text(
        encoding="utf-8"
    )

    required = (
        "System Readiness",
        "Mandatory Services",
        "Observability Health",
        "Persistence &amp; Recovery",
        "Configuration Identity",
        "Execution Boundary",
        "Diagnostic Capabilities",
    )

    for text in required:
        assert text in html


def test_health_diagnostics_ui_uses_authoritative_api():
    javascript = (
        STATIC_ROOT
        / "health-diagnostics.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        '"/api/v1/health-diagnostics"'
        in javascript
    )

    forbidden_endpoints = (
        "/run-diagnostics",
        "/resolve-alert",
        "/restore",
        "/prepare-update",
        "/health/mutate",
    )

    for endpoint in forbidden_endpoints:
        assert endpoint not in javascript


def test_health_diagnostics_ui_has_no_mutating_controls():
    html = (
        STATIC_ROOT
        / "health-diagnostics.html"
    ).read_text(
        encoding="utf-8"
    ).lower()

    forbidden = (
        "run diagnostics",
        "resolve alert",
        "prepare update",
        "restore state",
        "mutate health",
        "broker login",
        "account login",
        "place order",
        "submit trade",
    )

    for text in forbidden:
        assert text not in html


def test_health_diagnostics_navigation_is_enabled():
    pages = (
        "index.html",
        "configuration.html",
        "research-controls.html",
        "dataset-replay.html",
        "observability.html",
        "persistence-recovery.html",
        "health-diagnostics.html",
    )

    for page in pages:
        body = (
            STATIC_ROOT
            / page
        ).read_text(
            encoding="utf-8"
        )

        assert (
            'href="/health-diagnostics"'
            in body
        )


def test_health_diagnostics_page_preserves_research_boundary():
    html = (
        STATIC_ROOT
        / "health-diagnostics.html"
    ).read_text(
        encoding="utf-8"
    )

    javascript = (
        STATIC_ROOT
        / "health-diagnostics.js"
    ).read_text(
        encoding="utf-8"
    )

    combined = (
        html
        + "\n"
        + javascript
    ).lower()

    forbidden = (
        "financial execution available",
        "broker connectivity available",
        "account connectivity available",
        "live trading",
        "demo trading",
    )

    for text in forbidden:
        assert text not in combined
