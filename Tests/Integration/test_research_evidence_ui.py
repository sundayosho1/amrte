from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from amrte.web.app import create_app


STATIC_ROOT = (
    Path(__file__).resolve()
    .parents[2]
    / "src"
    / "amrte"
    / "web"
    / "static"
)


def _client():
    return TestClient(
        create_app()
    )


def test_research_evidence_page_is_reachable():
    with _client() as client:
        response = client.get(
            "/research-evidence"
        )

        assert response.status_code == 200

        assert (
            "text/html"
            in response.headers[
                "content-type"
            ]
        )

        html = response.text

        assert (
            "Research Evidence"
            in html
        )

        assert "READ-ONLY" in html
        assert "RESEARCH-ONLY" in html


def test_research_evidence_static_assets_exist():
    html = (
        STATIC_ROOT
        / "research-evidence.html"
    )

    javascript = (
        STATIC_ROOT
        / "research-evidence.js"
    )

    assert html.is_file()
    assert javascript.is_file()

    body = html.read_text(
        encoding="utf-8"
    )

    assert (
        "/static/console.css"
        in body
    )

    assert (
        "/static/research-evidence.js"
        in body
    )


def test_research_evidence_html_uses_canonical_shell():
    html = (
        STATIC_ROOT
        / "research-evidence.html"
    ).read_text(
        encoding="utf-8"
    )

    required = (
        'class="shell"',
        'class="sidebar"',
        'class="nav"',
        'class="main"',
        'class="topbar"',
        'href="/research-evidence"',
        'class="nav-item active"',
    )

    for marker in required:
        assert marker in html


def test_research_evidence_ui_contains_required_sections():
    html = (
        STATIC_ROOT
        / "research-evidence.html"
    ).read_text(
        encoding="utf-8"
    )

    required = (
        "Research Evidence &amp; Analytics",
        "Capability Readiness",
        "Runtime Identity",
        "Configuration Identity",
        "Execution Boundary",
        "Evidence Availability",
    )

    for marker in required:
        assert marker in html


def test_research_evidence_ui_declares_three_distinct_states():
    html = (
        STATIC_ROOT
        / "research-evidence.html"
    ).read_text(
        encoding="utf-8"
    )

    required = (
        "Implemented",
        "Runtime Active",
        "Evidence Available",
    )

    for marker in required:
        assert marker in html


def test_research_evidence_ui_uses_authoritative_read_only_api():
    script = (
        STATIC_ROOT
        / "research-evidence.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        '"/api/v1/research-evidence"'
        in script
        or
        "'/api/v1/research-evidence'"
        in script
    )

    assert "fetch(" in script

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

    for marker in forbidden_methods:
        assert marker not in script


def test_research_evidence_ui_has_no_execution_or_mutation_controls():
    html = (
        STATIC_ROOT
        / "research-evidence.html"
    ).read_text(
        encoding="utf-8"
    ).lower()

    script = (
        STATIC_ROOT
        / "research-evidence.js"
    ).read_text(
        encoding="utf-8"
    ).lower()

    combined = (
        html
        + "\n"
        + script
    )

    forbidden = (
        "run experiment",
        "start experiment",
        "execute experiment",
        "run analytics",
        "generate analytics",
        "evaluate strategy",
        "process evidence",
        "restore state",
        "create checkpoint",
        "delete checkpoint",
        "connect broker",
        "connect account",
        "place order",
        "submit order",
        "submit trade",
        "enable execution",
    )

    for marker in forbidden:
        assert marker not in combined

    assert "<form" not in html


def test_research_evidence_ui_does_not_fabricate_results():
    html = (
        STATIC_ROOT
        / "research-evidence.html"
    ).read_text(
        encoding="utf-8"
    ).lower()

    script = (
        STATIC_ROOT
        / "research-evidence.js"
    ).read_text(
        encoding="utf-8"
    ).lower()

    combined = (
        html
        + "\n"
        + script
    )

    forbidden = (
        "win_rate",
        "win rate",
        "expectancy",
        "performance_score",
        "performance score",
        "validation_score",
        "validation score",
        "experiment_result",
        "experiment result",
        "robustness_score",
        "robustness score",
        "profitability",
        "roi",
    )

    for marker in forbidden:
        assert marker not in combined


def test_research_evidence_ui_projects_all_capabilities():
    script = (
        STATIC_ROOT
        / "research-evidence.js"
    ).read_text(
        encoding="utf-8"
    )

    required = (
        "research_performance_analytics",
        "deterministic_experiments",
        "robustness_validation",
        "research_lifecycle",
        "observation_quality",
        "research_reliability",
        "temporal_quality_protection",
        "system_safety",
    )

    for marker in required:
        assert marker in script


def test_research_evidence_navigation_is_enabled_across_console():
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
    )

    for name in pages:
        path = STATIC_ROOT / name

        assert path.exists()

        html = path.read_text(
            encoding="utf-8"
        )

        assert (
            'href="/research-evidence"'
            in html
        )

        anchor_start = html.find(
            'href="/research-evidence"'
        )

        assert anchor_start >= 0

        context = html[
            max(
                0,
                anchor_start - 120,
            ):
            anchor_start + 120
        ]

        assert (
            "disabled"
            not in context.lower()
        )


def test_research_evidence_ui_preserves_execution_prohibition():
    html = (
        STATIC_ROOT
        / "research-evidence.html"
    ).read_text(
        encoding="utf-8"
    ).lower()

    script = (
        STATIC_ROOT
        / "research-evidence.js"
    ).read_text(
        encoding="utf-8"
    ).lower()

    combined = (
        html
        + "\n"
        + script
    )

    assert "prohibited" in combined

    forbidden = (
        "financial execution available",
        "broker connectivity available",
        "account connectivity available",
        "live trading",
        "demo trading",
        "broker login",
        "account login",
        "api key",
        "access token",
    )

    for marker in forbidden:
        assert marker not in combined
