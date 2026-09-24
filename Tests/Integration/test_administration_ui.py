from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from amrte.web.app import create_app


STATIC = (
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


def test_administration_page_exists():
    with _client() as client:
        response = client.get(
            "/administration"
        )

        assert response.status_code == 200
        assert (
            "text/html"
            in response.headers[
                "content-type"
            ]
        )


def test_administration_html_uses_canonical_shell():
    html = (
        STATIC
        / "administration.html"
    ).read_text(
        encoding="utf-8"
    )

    assert 'class="shell"' in html
    assert 'class="sidebar"' in html
    assert 'class="nav"' in html
    assert 'class="main"' in html
    assert 'class="topbar"' in html

    assert (
        'href="/administration"'
        in html
    )

    assert (
        'class="nav-item active"'
        in html
    )


def test_administration_html_declares_read_only_boundary():
    html = (
        STATIC
        / "administration.html"
    ).read_text(
        encoding="utf-8"
    ).lower()

    assert "administration" in html
    assert "read-only" in html
    assert "research" in html

    assert (
        "/static/administration.js"
        in html
    )

    assert (
        "/static/console.css"
        in html
    )


def test_administration_javascript_uses_read_only_api():
    script = (
        STATIC
        / "administration.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        '"/api/v1/administration"'
        in script
        or
        "'/api/v1/administration'"
        in script
    )

    assert "fetch(" in script

    forbidden = (
        "method: 'POST'",
        'method: "POST"',
        "method: 'PUT'",
        'method: "PUT"',
        "method: 'PATCH'",
        'method: "PATCH"',
        "method: 'DELETE'",
        'method: "DELETE"',
    )

    for fragment in forbidden:
        assert fragment not in script


def test_administration_ui_has_no_mutating_controls():
    html = (
        STATIC
        / "administration.html"
    ).read_text(
        encoding="utf-8"
    ).lower()

    forbidden = (
        "enable execution",
        "connect broker",
        "connect account",
        "restore state",
        "delete checkpoint",
        "quarantine checkpoint",
        "register service",
        "replace service",
        "edit configuration",
        "save configuration",
        "run diagnostics",
    )

    for fragment in forbidden:
        assert fragment not in html


def test_administration_navigation_is_enabled_across_console():
    pages = (
        "index.html",
        "configuration.html",
        "research-controls.html",
        "dataset-replay.html",
        "observability.html",
        "persistence-recovery.html",
        "health-diagnostics.html",
        "administration.html",
    )

    for name in pages:
        html = (
            STATIC / name
        ).read_text(
            encoding="utf-8"
        )

        assert (
            'href="/administration"'
            in html
        )

        anchor_start = html.find(
            'href="/administration"'
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


def test_administration_ui_preserves_execution_prohibition():
    html = (
        STATIC
        / "administration.html"
    ).read_text(
        encoding="utf-8"
    ).lower()

    script = (
        STATIC
        / "administration.js"
    ).read_text(
        encoding="utf-8"
    ).lower()

    combined = html + script

    assert "prohibited" in combined

    forbidden = (
        "live trading",
        "demo trading",
        "place order",
        "submit order",
        "broker login",
        "account login",
        "api key",
        "access token",
    )

    for fragment in forbidden:
        assert fragment not in combined
