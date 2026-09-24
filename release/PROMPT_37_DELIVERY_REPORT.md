# AMRTE PROMPT 37 — GIT-NATIVE BASELINE & REPRODUCIBILITY DELIVERY REPORT

## A. Result

```text
ACCEPTED WITH LIMITATIONS
```

Limitations: native Windows qualification was not performed; the resolved
environment identity is derived from the repository lock file and the Linux
verification environment; a tracked manifest cannot contain the final commit
that contains itself without self-reference.

## B. Starting Git Baseline

```text
Repository:            https://github.com/sundayosho1/amrte
Starting Branch:       main
Starting Commit:       7de2c58d24b1bd005405fa3a8e230b0749ace69c
Starting Working Tree: CLEAN
```

## C. Starting Application Baseline

```text
Package:                  amrte-research-core
Version:                  0.27.0
Python Requirement:       >=3.11
Historical Test Baseline: 1,110 passed / 0 failed / 0 skipped
```

## D. Pre-Implementation Verification

```text
Environment:      Linux-6.12.94+-x86_64-with-glibc2.39 / CPython 3.12.3
Tests Collected:  1,110
Passed:           1,110
Failed:           0
Skipped:          0
Warnings:         0
Duration:         12.89s
```

The first isolated run exposed undeclared test tooling: `pytest` was absent and
current Starlette TestClient required `httpx2`. Prompt 37 records this as a
dependency reproducibility gap and addresses it with a test extra plus
`requirements.lock`.

## E. Repository Classification

| Area | Classification |
| --- | --- |
| `src/amrte/` | Application source |
| `Tests/` | Automated tests |
| `pyproject.toml`, `requirements.lock` | Dependency/configuration declarations |
| `Docs/`, `documentation/`, `delivery reports/` | Documentation and historical reports |
| `src/amrte/web/static/` | Frontend/static assets |
| `tools/` | Repository verification tooling |
| `data/*.py` | Tracked research/proof source fixtures |
| `data/logs/`, `data/state/` | Ignored mutable runtime logs/checkpoints |
| `.venv/`, `__pycache__/`, `.pytest_cache/`, `*.egg-info/` | Ignored generated/local cache material |
| `release/` | Machine-readable release evidence and delivery reports |

## F. Version Authority

Package version authority:

```text
pyproject.toml [project].version = 0.27.0
```

Application/runtime version authority:

```text
src/amrte/core/constants.py AMRTE_VERSION = 0.27.0
```

Active runtime and web projections now derive from `AMRTE_VERSION`. Historical
`*.pre-*` snapshots and static display text are classified as non-authoritative.

## G. Source Identity

```text
Canonical Source Definition:
  Deterministic SHA-256 over normalized repository-relative paths and canonical
  file bytes from non-excluded workspace files.

Source Content SHA-256:
  e1216d30d9e92b288c89c3ca5d9f4c8842cdba77455059c423a595668ed5da2a

Included Scope:
  Application source, tests, docs, tooling, dependency declarations,
  configuration, static assets, tracked data/*.py source fixtures.

Excluded Scope:
  .git/, virtual environments, caches, build/dist, runtime logs/state,
  checkpoints, release evidence, temporary files, archives, generated cache
  directories.
```

## H. Git Identity

```text
Parent Commit:          7de2c58d24b1bd005405fa3a8e230b0749ace69c
Implementation Commit:  Recorded by Git after this report is committed
Branch:                 cursor/prompt-37-baseline-provenance-b31e
```

The manifest records the parent commit with `git_commit_verification:
ancestor`. The final implementation commit is reported by Git history and the
final delivery summary.

## I. Dependency Identity

```text
Dependency Declaration SHA-256:
  6816de3b03f12084bf85bdc927075c7df8c37b41e16a3b1a6b75bbe36b67cfb9

Lock Mechanism:
  requirements.lock constraints file plus pyproject optional test extra.

Resolved Environment Identity:
  c040b7b8c149049bc2ffaa4cabed01e548b4b3b49d339debc715fc0f02a25539
```

`DependencyDeclarationIdentity` is distinct from
`ResolvedEnvironmentIdentity`.

## J. Environment

```text
OS:           Linux-6.12.94+-x86_64-with-glibc2.39
Architecture: x86_64
Python:       CPython 3.12.3
pip/tooling:  pip 26.2.1 inside .venv; setuptools build backend
```

## K. Configuration Identity

```text
Configuration Schema Version:  1.0
Configuration Schema SHA-256:  2e2607346bce7ed1e35ee76ab887f6c1e492b1f794574ee9eaaec3efdd68662d
```

Configuration authority remains `MasterConfigurationEngine` and
`MasterConfigurationProvider`; Prompt 37 does not introduce a new configuration
framework.

## L. Schema Inventory

| Schema | Current Version | Authority | Persistence Impact | Compatibility / Migration |
| --- | --- | --- | --- | --- |
| Configuration | 1.0 | `CONFIG_SCHEMA_VERSION`, `config_schema.py` | Configuration snapshots | Current/compatible/ migration-required/incompatible classification |
| State | 1.0 | `STATE_SCHEMA_VERSION` | Checkpoint state payloads | Current/compatible/migration-required/incompatible classification |
| Checkpoint format | 1.0 | `PERSISTENCE_FORMAT_VERSION` | Local checkpoint files | Exact persistence-format match required |
| Simulation | 1.0 | `SIMULATION_SCHEMA_VERSION` | Simulation/replay records | Module-level restore validation |
| Audit/events | UNVERSIONED | `StructuredEvent`, event codes | JSONL audit/event logs | Hash-chain/event-code validation, no explicit schema version |
| Web/API | UNVERSIONED plus `/api/v1` route | FastAPI app | API payloads | No formal API migration mechanism |
| Dataset/replay | Mixed module versions | Market/event/replay modules | Dataset fingerprints, replay descriptors | Deterministic identities; no universal schema registry |
| Research evidence | UNVERSIONED projection | Web evidence module | Read-only API/UI evidence | No persistent schema migration in Prompt 37 |

## M. Release Manifest

```text
Path:   release/baseline.json
Schema: manifest_schema_version 1.0
```

## N. Baseline Verification

```bash
python tools/verify_baseline.py verify --manifest release/baseline.json
```

Result:

```text
PASSED
Mismatches: []
```

## O. Release Artifact

```text
Filename:        amrte-research-core-0.27.0-prompt37.zip
SHA-256:         96063bda549f1fa6d9d77a3062004b69d384c6b605b73c06d3726d6b628b8a8f
Source Identity: e1216d30d9e92b288c89c3ca5d9f4c8842cdba77455059c423a595668ed5da2a
Git Commit:      Parent recorded in manifest; implementation commit recorded by Git after commit
```

The archive is generated under `release/artifacts/` and ignored by Git as a
binary release artifact; its checksum is recorded in `release/baseline.json`.

## P. Files Added

| File | Purpose |
| --- | --- |
| `src/amrte/operations/provenance.py` | Prompt 37 provenance, identity, manifest, verifier, and archive implementation |
| `tools/verify_baseline.py` | CLI entry point for inspect/generate/verify/archive |
| `Tests/Unit/test_provenance_baseline.py` | Focused Prompt 37 tests |
| `requirements.lock` | Reproducible dependency constraints/lock |
| `Docs/PROMPT_37_REPRODUCIBILITY.md` | Reproduction, verification, release, rollback documentation |
| `release/baseline.json` | Machine-readable baseline manifest |
| `release/PROMPT_37_DELIVERY_REPORT.md` | Prompt 37 delivery evidence |

## Q. Files Modified

| File | Purpose | Why Required |
| --- | --- | --- |
| `pyproject.toml` | Added `test` optional dependency extra | Declares existing test-suite dependencies (`pytest`, `httpx2`) |
| `src/amrte/operations/runtime.py` | Derive runtime `VERSION` from `AMRTE_VERSION` | Version authority hardening |
| `src/amrte/web/app.py` | Derive FastAPI version from `AMRTE_VERSION` | Version authority hardening |
| `src/amrte/web/administration.py` | Derive projection version from `AMRTE_VERSION` | Version authority hardening |
| `src/amrte/web/dataset_replay.py` | Derive projection version from `AMRTE_VERSION` | Version authority hardening |
| `src/amrte/web/health_diagnostics.py` | Derive projection version from `AMRTE_VERSION` | Version authority hardening |
| `src/amrte/web/research_governance.py` | Derive projection version from `AMRTE_VERSION` | Version authority hardening |

## R. Focused Tests

```text
Collected: 22
Passed:    22
Failed:    0
Skipped:   0
Warnings:  0
```

Combined focused/checkpoint run:

```text
55 passed in 0.53s
```

## S. Full Regression

```text
Historical Comparison:
1,110 passed

Current Pre-Implementation:
1,110 passed / 0 failed / 0 skipped / 12.89s

Final:
Collected: 1,132
Passed:    1,132
Failed:    0
Skipped:   0
Warnings:  0
Duration:  13.17s
```

## T. Checkpoint/Recovery Regression

Relevant checkpoint/recovery tests:

```text
Tests/Unit/test_persistence.py
Tests/Unit/test_recovery.py
Tests/Integration/test_persistence_recovery.py
Tests/Integration/test_runtime_recovery_epoch.py

Included in combined focused/checkpoint run: 55 passed
```

## U. Windows Portability

```text
Static Portability Review: PASS
Native Windows Qualification: NOT VERIFIED
```

Prompt 37 code uses `pathlib`, relative path normalization, and standard
library hashing/JSON/ZIP behavior. No hard-coded `/tmp`, `/home`, or developer
workspace paths were introduced.

## V. Secret-Safety Scan

Static keyword scan found no tracked secret values. Matches were confined to
redaction logic, test fixtures, `.gitignore`, and documentation references to
secret-safety policy.

## W. Static Architecture Scan

No duplicate runtime, configuration, or persistence authority was introduced.
The verifier does not start FastAPI, `PersistentResearchRuntime`, or AMRTE
research modules. No broker/account connectivity, credential collection,
external market polling, or financial execution capability was added.

## X. Migration Status

```text
Database:      NONE
State:         NONE
Checkpoint:    NONE
Configuration: NONE
Dataset:       NONE
API:           NONE
```

## Y. Rollback

Pre-Prompt-37 Git baseline:

```text
7de2c58d24b1bd005405fa3a8e230b0749ace69c
```

Source rollback can use normal Git checkout/reset/revert workflows. Persistent
state and checkpoints are separate runtime artifacts; source rollback does not
automatically roll back `data/state` checkpoint contents.

## Z. Known Limitations

- Native Windows execution was not performed.
- The resolved environment identity is lock-file based and verified on Linux.
- `release/baseline.json` verifies Git ancestry rather than exact final commit
  equality to avoid impossible tracked-manifest self-reference.
- Web/API and audit event payloads remain partially unversioned.
- Historical `*.pre-*` snapshot files still contain display version literals.

## AA. Gap Scan

```text
P0: None identified.
P1: No explicit schema version for all Web/API and audit event payload contracts.
P2: Native Windows Server/VPS qualification remains outstanding.
P2: Lock identity is not a universal cross-platform artifact hash proof.
P3: Historical pre-snapshot files retain hardcoded display versions.
```

## AB. New Authoritative Baseline

```text
Application Version:             0.27.0
Package:                         amrte-research-core
Git Commit:                      Recorded by final Prompt 37 Git commit
Source Content SHA-256:          e1216d30d9e92b288c89c3ca5d9f4c8842cdba77455059c423a595668ed5da2a
Dependency Declaration SHA-256:  6816de3b03f12084bf85bdc927075c7df8c37b41e16a3b1a6b75bbe36b67cfb9
Resolved Dependency Identity:    c040b7b8c149049bc2ffaa4cabed01e548b4b3b49d339debc715fc0f02a25539
Release Artifact SHA-256:        96063bda549f1fa6d9d77a3062004b69d384c6b605b73c06d3726d6b628b8a8f
Tests:                           1,132 passed / 0 failed / 0 skipped
Verified Python:                 CPython 3.12.3
Verified Platform:               Linux-6.12.94+-x86_64-with-glibc2.39
Windows Native Qualification:    NOT VERIFIED
Financial Execution Capability:  PROHIBITED / NONE
```

## AC. Prompt 38 Readiness

```text
READY FOR PROMPT 38
```

Prompt 37 stops at release/provenance/reproducibility hardening and does not
implement Prompt 38 runtime composition work.
