from pathlib import Path

from fastapi.testclient import TestClient

from amrte.operations.runtime import (
    PersistentResearchRuntime,
)
from amrte.web.app import create_app


STATIC_ROOT = (
    Path(__file__).resolve()
    .parents[2]
    / "src"
    / "amrte"
    / "web"
    / "static"
)


def _runtime_factory(
    tmp_path: Path,
):
    state_root = tmp_path / "state"
    log_path = (
        tmp_path
        / "logs"
        / "amrte.jsonl"
    )

    def factory():
        return PersistentResearchRuntime(
            state_root=state_root,
            log_path=log_path,
        )

    return factory


def test_persistence_recovery_page_is_reachable(
    tmp_path,
):
    app = create_app(
        runtime_factory=_runtime_factory(
            tmp_path
        )
    )

    with TestClient(app) as client:
        response = client.get(
            "/persistence-recovery"
        )

        assert response.status_code == 200

        html = response.text

        assert (
            "Persistence &amp; Recovery"
            in html
            or "Persistence & Recovery"
            in html
        )

        assert 'class="nav-item active"' in html

        assert (
            "/static/console.css"
            in html
        )

        assert (
            "/static/persistence-recovery.js"
            in html
        )

        assert (
            "READ ONLY"
            in html
        )

        assert (
            "checkpoint-history"
            in html
        )

        assert (
            "recovery-readiness"
            in html
        )

        assert (
            "execution-boundary"
            in html
        )


def test_persistence_recovery_ui_uses_read_only_api():
    script_path = (
        STATIC_ROOT
        / "persistence-recovery.js"
    )

    assert script_path.exists()

    script = script_path.read_text(
        encoding="utf-8"
    )

    assert (
        "/api/v1/persistence-recovery"
        in script
    )

    assert (
        'method: "GET"'
        in script
        or "method: 'GET'"
        in script
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

    for marker in forbidden_methods:
        assert marker not in script

    forbidden_actions = (
        "createCheckpoint",
        "restoreCheckpoint",
        "rollbackCheckpoint",
        "quarantineCheckpoint",
        "deleteCheckpoint",
        "executeRecovery",
    )

    for marker in forbidden_actions:
        assert marker not in script


def test_persistence_recovery_ui_does_not_expose_state_payload():
    html_path = (
        STATIC_ROOT
        / "persistence-recovery.html"
    )

    script_path = (
        STATIC_ROOT
        / "persistence-recovery.js"
    )

    assert html_path.exists()
    assert script_path.exists()

    combined = (
        html_path.read_text(
            encoding="utf-8"
        )
        + "\n"
        + script_path.read_text(
            encoding="utf-8"
        )
    ).lower()

    forbidden = (
        "state_payload",
        "committed_idempotency_keys",
        "known_owner_ids",
        "expected_object_ids",
        "actual_object_ids",
    )

    for marker in forbidden:
        assert marker not in combined


def test_persistence_recovery_navigation_is_enabled():
    pages = (
        "index.html",
        "configuration.html",
        "research-controls.html",
        "dataset-replay.html",
        "observability.html",
        "persistence-recovery.html",
    )

    for name in pages:
        path = STATIC_ROOT / name

        assert path.exists()

        html = path.read_text(
            encoding="utf-8"
        )

        assert (
            'href="/persistence-recovery"'
            in html
        )

        persistence_lines = [
            line
            for line in html.splitlines()
            if (
                "Persistence & Recovery"
                in line
                or "Persistence &amp; Recovery"
                in line
                or "/persistence-recovery"
                in line
            )
        ]

        assert persistence_lines

        relevant = "\n".join(
            persistence_lines
        )

        if name != "persistence-recovery.html":
            assert (
                "disabled"
                not in relevant.lower()
            )


def test_persistence_recovery_ui_contains_no_mutation_controls():
    html_path = (
        STATIC_ROOT
        / "persistence-recovery.html"
    )

    assert html_path.exists()

    html = html_path.read_text(
        encoding="utf-8"
    ).lower()

    forbidden_controls = (
        "create checkpoint",
        "restore checkpoint",
        "rollback checkpoint",
        "quarantine checkpoint",
        "delete checkpoint",
        "execute recovery",
        "run recovery",
    )

    for marker in forbidden_controls:
        assert marker not in html

    assert "<form" not in html
