from pathlib import Path

from fastapi.testclient import TestClient

from amrte.web.app import create_app


PAGE = "/research-lifecycle-quality"
API = "/api/v1/research-lifecycle-quality"

STATIC_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "amrte"
    / "web"
    / "static"
)

HTML_PATH = STATIC_ROOT / "research-lifecycle-quality.html"
JS_PATH = STATIC_ROOT / "research-lifecycle-quality.js"


def test_research_lifecycle_quality_page_is_registered():
    app = create_app()

    with TestClient(app) as client:
        response = client.get(PAGE)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_research_lifecycle_quality_html_exists():
    assert HTML_PATH.exists()


def test_research_lifecycle_quality_javascript_exists():
    assert JS_PATH.exists()


def test_page_identifies_product_and_research_boundary():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "Research Lifecycle &amp; Quality Assurance" in html
    assert "RESEARCH" in html
    assert "Read-only" in html


def test_page_exposes_all_five_assurance_domains():
    html = HTML_PATH.read_text(encoding="utf-8")

    required = (
        "Research Lifecycle",
        "Observation Quality",
        "Research Reliability",
        "Temporal Quality",
        "System Safety",
    )

    for label in required:
        assert label in html


def test_page_distinguishes_implementation_from_runtime_state():
    html = HTML_PATH.read_text(encoding="utf-8")

    required = (
        "IMPLEMENTED",
        "Runtime Active",
        "Runtime Authority",
        "Current State",
        "UNAVAILABLE",
    )

    for label in required:
        assert label in html


def test_page_contains_explicit_current_state_limitation():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "Current engine state is unavailable" in html


def test_page_contains_research_only_safety_boundary():
    html = HTML_PATH.read_text(encoding="utf-8")

    required = (
        "Financial Execution",
        "Broker Connectivity",
        "Account Connectivity",
        "Order Execution",
        "Live Execution",
        "Demo Execution",
    )

    for label in required:
        assert label in html


def test_page_contains_no_mutating_controls():
    html = HTML_PATH.read_text(encoding="utf-8").lower()

    forbidden = (
        "<form",
        'type="submit"',
        "activate engine",
        "transition state",
        "promote",
        "restore checkpoint",
        "restore state",
        "recover now",
        "start recovery",
        "run recovery",
        "trigger recovery",
        "initiate recovery",
        "request recovery",
        "reset state",
        "reset engine",
        "execute order",
    )

    for token in forbidden:
        assert token not in html


def test_javascript_reads_only_slice_12_get_endpoint():
    javascript = JS_PATH.read_text(encoding="utf-8")

    assert API in javascript
    assert "fetch(" in javascript

    forbidden = (
        'method: "POST"',
        "method: 'POST'",
        'method: "PUT"',
        "method: 'PUT'",
        'method: "PATCH"',
        "method: 'PATCH'",
        'method: "DELETE"',
        "method: 'DELETE'",
    )

    for token in forbidden:
        assert token not in javascript


def test_javascript_does_not_claim_runtime_state():
    javascript = JS_PATH.read_text(encoding="utf-8")

    assert "current_state_available" in javascript
    assert "runtime_active" in javascript
    assert "runtime_authority" in javascript


def test_page_uses_shared_console_stylesheet():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "/static/console.css" in html


def test_page_loads_slice_specific_javascript():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "/static/research-lifecycle-quality.js" in html


def test_existing_api_remains_get_only():
    app = create_app()

    with TestClient(app) as client:
        get_response = client.get(API)
        post_response = client.post(API)
        put_response = client.put(API)
        patch_response = client.patch(API)
        delete_response = client.delete(API)

    assert get_response.status_code == 200
    assert post_response.status_code == 405
    assert put_response.status_code == 405
    assert patch_response.status_code == 405
    assert delete_response.status_code == 405
