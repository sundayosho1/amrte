from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from amrte.core.config_schema import SETTING_DEFINITIONS
from amrte.core.constants import (
    AMRTE_VERSION,
    CONFIG_SCHEMA_VERSION,
    SIMULATION_SCHEMA_VERSION,
    STATE_SCHEMA_VERSION,
)
from amrte.core.persistence import PERSISTENCE_FORMAT_VERSION
from amrte.core.persistence_types import Checkpoint


MANIFEST_SCHEMA_VERSION = "1.0"
SOURCE_IDENTITY_ALGORITHM = "sha256"
SOURCE_IDENTITY_EXCLUDED_PREFIXES = (
    ".git/",
    ".venv/",
    "venv/",
    "env/",
    "ENV/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    "htmlcov/",
    "build/",
    "dist/",
    "data/logs/",
    "data/runtime/",
    "data/state/",
    "data/backup/",
    "data/state-repair-proof/",
    "release/",
    "checkpoints/",
    "runtime/",
    "tmp/",
    "temp/",
)
SOURCE_IDENTITY_EXCLUDED_NAMES = {
    "__pycache__",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
}
SOURCE_IDENTITY_EXCLUDED_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".log",
    ".tmp",
    ".temp",
    ".bak",
    ".swp",
    ".swo",
    ".prof",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".egg-info",
)
DEPENDENCY_DECLARATION_FILES = (
    "pyproject.toml",
    "requirements.lock",
)


class MismatchCategory(str, Enum):
    GIT_COMMIT_MISMATCH = "GIT_COMMIT_MISMATCH"
    SOURCE_CONTENT_MISMATCH = "SOURCE_CONTENT_MISMATCH"
    DEPENDENCY_DECLARATION_MISMATCH = (
        "DEPENDENCY_DECLARATION_MISMATCH"
    )
    RESOLVED_ENVIRONMENT_MISMATCH = "RESOLVED_ENVIRONMENT_MISMATCH"
    CONFIG_SCHEMA_MISMATCH = "CONFIG_SCHEMA_MISMATCH"
    STATE_SCHEMA_MISMATCH = "STATE_SCHEMA_MISMATCH"
    CHECKPOINT_SCHEMA_MISMATCH = "CHECKPOINT_SCHEMA_MISMATCH"
    MANIFEST_SCHEMA_UNSUPPORTED = "MANIFEST_SCHEMA_UNSUPPORTED"
    MANIFEST_FIELD_MISSING = "MANIFEST_FIELD_MISSING"


@dataclass(frozen=True)
class BaselineMismatch:
    category: MismatchCategory
    expected: str
    actual: str
    subject: str

    def to_dict(self) -> dict[str, str]:
        return {
            "category": self.category.value,
            "subject": self.subject,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass(frozen=True)
class IdentityResult:
    sha256: str
    files: tuple[str, ...]


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def normalize_relative_path(path: str | Path) -> str:
    raw = str(path).replace("\\", "/")
    normalized = PurePosixPath(raw).as_posix()
    if normalized in ("", "."):
        raise ValueError("relative path is empty")
    if normalized.startswith("../") or normalized == "..":
        raise ValueError(f"path escapes repository root: {path}")
    if normalized.startswith("/"):
        raise ValueError(f"path must be relative: {path}")
    return normalized


def _is_excluded_path(relative_path: str) -> bool:
    path = normalize_relative_path(relative_path)
    name = PurePosixPath(path).name
    if name in SOURCE_IDENTITY_EXCLUDED_NAMES:
        return True
    if any(part == "__pycache__" for part in PurePosixPath(path).parts):
        return True
    if any(path == prefix[:-1] or path.startswith(prefix)
           for prefix in SOURCE_IDENTITY_EXCLUDED_PREFIXES):
        return True
    return path.endswith(SOURCE_IDENTITY_EXCLUDED_SUFFIXES)


def _walk_repository_files(root: Path) -> tuple[str, ...]:
    paths: list[str] = []
    for directory, names, files in os.walk(root):
        relative_directory = Path(directory).relative_to(root)
        normalized_directory = (
            "."
            if str(relative_directory) == "."
            else normalize_relative_path(relative_directory)
        )
        names[:] = [
            name
            for name in names
            if not _is_excluded_path(
                name
                if normalized_directory == "."
                else f"{normalized_directory}/{name}"
            )
        ]
        for file_name in files:
            relative = (
                file_name
                if normalized_directory == "."
                else f"{normalized_directory}/{file_name}"
            )
            if not _is_excluded_path(relative):
                paths.append(normalize_relative_path(relative))
    return tuple(sorted(paths))


def canonical_source_inventory(
    root: Path,
    paths: Iterable[str | Path] | None = None,
) -> tuple[str, ...]:
    root = Path(root)
    if paths is None:
        return _walk_repository_files(root)
    normalized = {
        normalize_relative_path(path)
        for path in paths
        if not _is_excluded_path(str(path))
    }
    return tuple(sorted(normalized))


def _canonical_file_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if b"\x00" in data:
        return data
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def fingerprint_files(root: Path, paths: Iterable[str | Path]) -> IdentityResult:
    root = Path(root)
    inventory = canonical_source_inventory(root, paths)
    digest = hashlib.sha256()
    for relative in inventory:
        file_path = root / relative
        if not file_path.is_file():
            raise FileNotFoundError(relative)
        data = _canonical_file_bytes(file_path)
        encoded_path = relative.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(len(data).to_bytes(16, "big"))
        digest.update(data)
    return IdentityResult(digest.hexdigest(), inventory)


def source_content_identity(root: Path) -> IdentityResult:
    return fingerprint_files(root, canonical_source_inventory(root))


def dependency_declaration_identity(root: Path) -> IdentityResult:
    paths = [
        path
        for path in DEPENDENCY_DECLARATION_FILES
        if (Path(root) / path).is_file()
    ]
    return fingerprint_files(Path(root), paths)


def _canonical_lock_lines(lock_text: str) -> tuple[str, ...]:
    lines = []
    for raw in lock_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return tuple(sorted(lines, key=str.casefold))


def resolved_environment_identity_from_lock(root: Path) -> str | None:
    lock_path = Path(root) / "requirements.lock"
    if not lock_path.is_file():
        return None
    payload = {
        "lock_file": "requirements.lock",
        "packages": _canonical_lock_lines(lock_path.read_text("utf-8")),
    }
    return sha256_text(canonical_json(payload))


def configuration_schema_identity() -> str:
    definitions = []
    for definition in sorted(SETTING_DEFINITIONS, key=lambda item: item.key):
        definitions.append(
            {
                "key": definition.key,
                "value_type": definition.value_type.__name__,
                "unit": definition.unit,
                "default": _jsonable(definition.default),
                "minimum": definition.minimum,
                "maximum": definition.maximum,
                "required": definition.required,
                "safety_critical": definition.safety_critical,
                "override_policy": definition.override_policy.name,
                "choices": _jsonable(definition.choices),
                "deprecated_replacement": definition.deprecated_replacement,
            }
        )
    return sha256_text(
        canonical_json(
            {
                "schema": "configuration",
                "schema_version": CONFIG_SCHEMA_VERSION,
                "settings": definitions,
            }
        )
    )


def state_schema_identity() -> str:
    return sha256_text(
        canonical_json(
            {
                "schema": "state",
                "state_schema_version": STATE_SCHEMA_VERSION,
                "simulation_schema_version": SIMULATION_SCHEMA_VERSION,
            }
        )
    )


def checkpoint_schema_identity() -> str:
    fields = [
        {
            "name": name,
            "type": str(field.type),
        }
        for name, field in Checkpoint.__dataclass_fields__.items()
    ]
    return sha256_text(
        canonical_json(
            {
                "schema": "checkpoint",
                "state_schema_version": STATE_SCHEMA_VERSION,
                "persistence_format_version": PERSISTENCE_FORMAT_VERSION,
                "fields": fields,
            }
        )
    )


def schema_identities() -> dict[str, str]:
    return {
        "configuration_schema_sha256": configuration_schema_identity(),
        "state_schema_sha256": state_schema_identity(),
        "checkpoint_schema_sha256": checkpoint_schema_identity(),
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable(nested)
            for key, nested in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if hasattr(value, "name") and hasattr(value, "value"):
        return value.name
    return value


def _run_git(root: Path, args: Sequence[str], check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def git_identity(root: Path) -> dict[str, str]:
    return {
        "branch": _run_git(root, ["branch", "--show-current"]),
        "commit": _run_git(root, ["rev-parse", "HEAD"]),
        "origin_main": _run_git(root, ["rev-parse", "origin/main"], check=False),
        "working_tree_status": _run_git(root, ["status", "--short"]),
    }


def is_git_ancestor(root: Path, expected_ancestor: str, actual: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", expected_ancestor, actual],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return result.returncode == 0


def verified_environment() -> dict[str, str]:
    return {
        "operating_system": platform.platform(),
        "architecture": platform.machine(),
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
    }


def build_baseline_manifest(
    root: Path,
    *,
    parent_git_commit: str,
    test_baseline: Mapping[str, Any],
    archive: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(root)
    source = source_content_identity(root)
    dependencies = dependency_declaration_identity(root)
    schemas = schema_identities()
    git = git_identity(root)
    return {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "project": "Adaptive Multi-Regime Trading Engine",
        "package": "amrte-research-core",
        "application_version": AMRTE_VERSION,
        "git_branch": git["branch"],
        "git_commit": parent_git_commit,
        "git_commit_verification": "ancestor",
        "current_generation_commit": git["commit"],
        "source_content_sha256": source.sha256,
        "source_identity_algorithm": SOURCE_IDENTITY_ALGORITHM,
        "source_identity_file_count": len(source.files),
        "source_identity_excluded_prefixes": SOURCE_IDENTITY_EXCLUDED_PREFIXES,
        "dependency_declaration_sha256": dependencies.sha256,
        "dependency_declaration_files": dependencies.files,
        "resolved_environment_identity": (
            resolved_environment_identity_from_lock(root)
        ),
        "python_requirement": ">=3.11",
        "configuration_schema_identity": schemas[
            "configuration_schema_sha256"
        ],
        "state_schema_identity": schemas["state_schema_sha256"],
        "checkpoint_schema_identity": schemas["checkpoint_schema_sha256"],
        "test_baseline": dict(test_baseline),
        "verified_environment": verified_environment(),
        "known_qualification_limits": {
            "native_windows_qualification": "NOT_VERIFIED",
            "resolved_lock_platform": (
                "Linux verification environment; Windows-only tzdata is "
                "pinned with a platform marker."
            ),
        },
        "financial_capability_boundary": {
            "execution": "PROHIBITED",
            "broker_connectivity": "UNAVAILABLE",
            "live_trading": "UNAVAILABLE",
            "demo_trading": "UNAVAILABLE",
        },
        "release_archive": dict(archive or {}),
    }


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_baseline(root: Path, manifest: Mapping[str, Any]) -> tuple[BaselineMismatch, ...]:
    mismatches: list[BaselineMismatch] = []
    if manifest.get("manifest_schema_version") != MANIFEST_SCHEMA_VERSION:
        return (
            BaselineMismatch(
                MismatchCategory.MANIFEST_SCHEMA_UNSUPPORTED,
                MANIFEST_SCHEMA_VERSION,
                str(manifest.get("manifest_schema_version")),
                "manifest_schema_version",
            ),
        )

    required = (
        "git_commit",
        "source_content_sha256",
        "dependency_declaration_sha256",
        "configuration_schema_identity",
        "state_schema_identity",
        "checkpoint_schema_identity",
    )
    for field in required:
        if field not in manifest:
            mismatches.append(
                BaselineMismatch(
                    MismatchCategory.MANIFEST_FIELD_MISSING,
                    "present",
                    "missing",
                    field,
                )
            )
    if mismatches:
        return tuple(mismatches)

    git = git_identity(root)
    expected_commit = str(manifest["git_commit"])
    policy = manifest.get("git_commit_verification", "exact")
    git_matches = (
        is_git_ancestor(root, expected_commit, git["commit"])
        if policy == "ancestor"
        else git["commit"] == expected_commit
    )
    if not git_matches:
        mismatches.append(
            BaselineMismatch(
                MismatchCategory.GIT_COMMIT_MISMATCH,
                expected_commit,
                git["commit"],
                "git_commit",
            )
        )

    source = source_content_identity(root).sha256
    if source != manifest["source_content_sha256"]:
        mismatches.append(
            BaselineMismatch(
                MismatchCategory.SOURCE_CONTENT_MISMATCH,
                str(manifest["source_content_sha256"]),
                source,
                "source_content_sha256",
            )
        )

    dependency = dependency_declaration_identity(root).sha256
    if dependency != manifest["dependency_declaration_sha256"]:
        mismatches.append(
            BaselineMismatch(
                MismatchCategory.DEPENDENCY_DECLARATION_MISMATCH,
                str(manifest["dependency_declaration_sha256"]),
                dependency,
                "dependency_declaration_sha256",
            )
        )

    resolved = resolved_environment_identity_from_lock(root)
    expected_resolved = manifest.get("resolved_environment_identity")
    if resolved != expected_resolved:
        mismatches.append(
            BaselineMismatch(
                MismatchCategory.RESOLVED_ENVIRONMENT_MISMATCH,
                str(expected_resolved),
                str(resolved),
                "resolved_environment_identity",
            )
        )

    schemas = schema_identities()
    checks = (
        (
            "configuration_schema_identity",
            "configuration_schema_sha256",
            MismatchCategory.CONFIG_SCHEMA_MISMATCH,
        ),
        (
            "state_schema_identity",
            "state_schema_sha256",
            MismatchCategory.STATE_SCHEMA_MISMATCH,
        ),
        (
            "checkpoint_schema_identity",
            "checkpoint_schema_sha256",
            MismatchCategory.CHECKPOINT_SCHEMA_MISMATCH,
        ),
    )
    for manifest_field, actual_field, category in checks:
        if manifest[manifest_field] != schemas[actual_field]:
            mismatches.append(
                BaselineMismatch(
                    category,
                    str(manifest[manifest_field]),
                    schemas[actual_field],
                    manifest_field,
                )
            )
    return tuple(mismatches)


def create_release_archive(
    root: Path,
    output_path: Path,
    *,
    version: str = AMRTE_VERSION,
) -> dict[str, Any]:
    root = Path(root)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    files = source_content_identity(root).files
    timestamp = (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in files:
            info = zipfile.ZipInfo(relative, timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, _canonical_file_bytes(root / relative))
    return {
        "filename": output_path.name,
        "sha256": sha256_bytes(output_path.read_bytes()),
        "format": "zip",
        "application_version": version,
        "included_file_count": len(files),
    }


def _parse_test_baseline(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    return json.loads(text)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AMRTE Prompt 37 baseline provenance tool"
    )
    parser.add_argument(
        "command",
        choices=("inspect", "generate", "verify", "archive"),
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--manifest", default="release/baseline.json")
    parser.add_argument("--parent-git-commit", default="")
    parser.add_argument("--test-baseline-json", default=None)
    parser.add_argument("--archive-path", default="")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    manifest_path = root / args.manifest

    if args.command == "inspect":
        payload = {
            "git": git_identity(root),
            "source": source_content_identity(root).__dict__,
            "dependency": dependency_declaration_identity(root).__dict__,
            "resolved_environment_identity": (
                resolved_environment_identity_from_lock(root)
            ),
            "schemas": schema_identities(),
            "environment": verified_environment(),
        }
        print(canonical_json(payload))
        return 0

    if args.command == "archive":
        if not args.archive_path:
            parser.error("--archive-path is required for archive")
        payload = create_release_archive(root, root / args.archive_path)
        print(canonical_json(payload))
        return 0

    if args.command == "generate":
        parent = args.parent_git_commit or git_identity(root)["commit"]
        archive = None
        if args.archive_path:
            archive = create_release_archive(root, root / args.archive_path)
        manifest = build_baseline_manifest(
            root,
            parent_git_commit=parent,
            test_baseline=_parse_test_baseline(args.test_baseline_json),
            archive=archive,
        )
        write_manifest(manifest_path, manifest)
        print(canonical_json({"manifest": str(manifest_path)}))
        return 0

    manifest = load_manifest(manifest_path)
    mismatches = verify_baseline(root, manifest)
    print(
        canonical_json(
            {
                "result": "PASSED" if not mismatches else "FAILED",
                "mismatches": [mismatch.to_dict() for mismatch in mismatches],
            }
        )
    )
    return 0 if not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
