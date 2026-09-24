from __future__ import annotations

import json
from pathlib import Path

import pytest

from amrte.app import build_engine
from amrte.operations import provenance


ROOT = Path(__file__).resolve().parents[2]
PARENT = "7de2c58d24b1bd005405fa3a8e230b0749ace69c"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def minimal_manifest() -> dict:
    return provenance.build_baseline_manifest(
        ROOT,
        parent_git_commit=provenance.git_identity(ROOT)["commit"],
        test_baseline={"tests_collected": 0, "tests_passed": 0},
    )


def test_canonical_source_inventory_orders_and_normalizes_paths(tmp_path):
    write(tmp_path / "b.py", "b\n")
    write(tmp_path / "a.py", "a\n")
    inventory = provenance.canonical_source_inventory(
        tmp_path,
        ("b.py", "folder\\c.py", "a.py"),
    )
    assert inventory == ("a.py", "b.py", "folder/c.py")


def test_source_fingerprint_is_deterministic(tmp_path):
    write(tmp_path / "a.py", "a\n")
    first = provenance.source_content_identity(tmp_path)
    second = provenance.source_content_identity(tmp_path)
    assert first == second


def test_source_change_changes_fingerprint(tmp_path):
    write(tmp_path / "a.py", "a\n")
    first = provenance.source_content_identity(tmp_path).sha256
    write(tmp_path / "a.py", "changed\n")
    assert provenance.source_content_identity(tmp_path).sha256 != first


def test_transient_excluded_files_do_not_change_fingerprint(tmp_path):
    write(tmp_path / "a.py", "a\n")
    first = provenance.source_content_identity(tmp_path).sha256
    write(tmp_path / ".pytest_cache" / "state", "ignored\n")
    write(tmp_path / "data" / "logs" / "amrte.jsonl", "ignored\n")
    write(tmp_path / "data" / "research-controlled-experiments" / "state.json", "ignored\n")
    write(tmp_path / "data" / "research-evidence-ledger" / "ledger.head.json", "ignored\n")
    write(tmp_path / "data" / "research-improvement-intelligence" / "state.json", "ignored\n")
    write(tmp_path / "data" / "research-outcome-performance" / "state.json", "ignored\n")
    assert provenance.source_content_identity(tmp_path).sha256 == first


def test_meaningful_included_file_changes_fingerprint(tmp_path):
    write(tmp_path / "data" / "fixture.py", "fixture = 1\n")
    first = provenance.source_content_identity(tmp_path).sha256
    write(tmp_path / "data" / "fixture.py", "fixture = 2\n")
    assert provenance.source_content_identity(tmp_path).sha256 != first


def test_dependency_declaration_fingerprint_is_deterministic(tmp_path):
    write(tmp_path / "pyproject.toml", "[project]\nname='x'\n")
    write(tmp_path / "requirements.lock", "a==1\n")
    first = provenance.dependency_declaration_identity(tmp_path)
    second = provenance.dependency_declaration_identity(tmp_path)
    assert first == second


def test_dependency_change_detection(tmp_path):
    write(tmp_path / "pyproject.toml", "[project]\nname='x'\n")
    first = provenance.dependency_declaration_identity(tmp_path).sha256
    write(tmp_path / "pyproject.toml", "[project]\nname='y'\n")
    assert provenance.dependency_declaration_identity(tmp_path).sha256 != first


def test_manifest_serialization_is_deterministic():
    left = provenance.canonical_json({"b": 1, "a": [2, None]})
    right = provenance.canonical_json({"a": [2, None], "b": 1})
    assert left == right == '{"a":[2,null],"b":1}'


def test_manifest_schema_validation_rejects_future_schema(tmp_path):
    mismatches = provenance.verify_baseline(
        tmp_path,
        {"manifest_schema_version": "999.0"},
    )
    assert mismatches[0].category is provenance.MismatchCategory.MANIFEST_SCHEMA_UNSUPPORTED


def test_git_identity_capture():
    identity = provenance.git_identity(ROOT)
    assert len(identity["commit"]) == 40
    assert identity["branch"]


def test_successful_baseline_verification():
    assert provenance.verify_baseline(ROOT, minimal_manifest()) == ()


def test_git_mismatch_detection():
    manifest = minimal_manifest()
    manifest["git_commit"] = "0" * 40
    manifest["git_commit_verification"] = "exact"
    mismatches = provenance.verify_baseline(ROOT, manifest)
    assert provenance.MismatchCategory.GIT_COMMIT_MISMATCH in {
        item.category for item in mismatches
    }


def test_source_mismatch_detection():
    manifest = minimal_manifest()
    manifest["source_content_sha256"] = "0" * 64
    mismatches = provenance.verify_baseline(ROOT, manifest)
    assert provenance.MismatchCategory.SOURCE_CONTENT_MISMATCH in {
        item.category for item in mismatches
    }


def test_dependency_mismatch_detection():
    manifest = minimal_manifest()
    manifest["dependency_declaration_sha256"] = "0" * 64
    mismatches = provenance.verify_baseline(ROOT, manifest)
    assert provenance.MismatchCategory.DEPENDENCY_DECLARATION_MISMATCH in {
        item.category for item in mismatches
    }


def test_configuration_schema_mismatch_handling():
    manifest = minimal_manifest()
    manifest["configuration_schema_identity"] = "0" * 64
    mismatches = provenance.verify_baseline(ROOT, manifest)
    assert provenance.MismatchCategory.CONFIG_SCHEMA_MISMATCH in {
        item.category for item in mismatches
    }


def test_unsupported_future_manifest_schema_rejection():
    mismatches = provenance.verify_baseline(
        ROOT,
        {"manifest_schema_version": "2.0"},
    )
    assert len(mismatches) == 1
    assert mismatches[0].category is provenance.MismatchCategory.MANIFEST_SCHEMA_UNSUPPORTED


def test_self_reference_protection_excludes_release_manifest(tmp_path):
    write(tmp_path / "src" / "a.py", "a\n")
    first = provenance.source_content_identity(tmp_path).sha256
    write(tmp_path / "release" / "baseline.json", json.dumps({"hash": first}))
    assert provenance.source_content_identity(tmp_path).sha256 == first


def test_path_normalization_rejects_absolute_and_parent_paths():
    with pytest.raises(ValueError):
        provenance.normalize_relative_path("/absolute")
    with pytest.raises(ValueError):
        provenance.normalize_relative_path("../escape")


def test_platform_neutral_line_ending_canonicalization(tmp_path):
    write(tmp_path / "a.txt", "one\ntwo\n")
    first = provenance.source_content_identity(tmp_path).sha256
    (tmp_path / "a.txt").write_bytes(b"one\r\ntwo\r\n")
    assert provenance.source_content_identity(tmp_path).sha256 == first


def test_verification_is_read_only(tmp_path):
    manifest = minimal_manifest()
    marker = tmp_path / "marker.txt"
    write(marker, "unchanged\n")
    before = marker.read_text(encoding="utf-8")
    provenance.verify_baseline(ROOT, manifest)
    assert marker.read_text(encoding="utf-8") == before


def test_resolved_environment_identity_uses_lock_canonical_lines(tmp_path):
    write(
        tmp_path / "requirements.lock",
        "# comment\nb==2\n\na==1\n",
    )
    first = provenance.resolved_environment_identity_from_lock(tmp_path)
    write(tmp_path / "requirements.lock", "a==1\nb==2\n")
    assert provenance.resolved_environment_identity_from_lock(tmp_path) == first


def test_execution_prohibition_preserved():
    engine = build_engine()
    execution = engine.registry.require("execution")
    assert type(execution).__name__ == "ProhibitedExecutionProvider"
    assert not execution.submit({"request": "blocked"}).success
