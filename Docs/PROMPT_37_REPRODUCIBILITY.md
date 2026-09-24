# AMRTE Prompt 37 Reproducibility and Release Governance

Prompt 37 establishes the Git-native development baseline for AMRTE
`amrte-research-core` v0.27.0. It does not activate research modules or change
the runtime authority. The baseline tooling is read-only unless `generate` or
`archive` is explicitly requested.

## Clone and checkout

```bash
git clone https://github.com/sundayosho1/amrte
cd amrte
git checkout 7de2c58d24b1bd005405fa3a8e230b0749ace69c
```

Prompt 37 development is based on the parent commit:

```text
7de2c58d24b1bd005405fa3a8e230b0749ace69c
```

## Python environment

AMRTE declares:

```text
Python >=3.11
```

Use an isolated environment. On Debian/Ubuntu systems the `python3-venv`
package may be required before creating a virtual environment.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
```

On Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Native Windows qualification is not performed by Prompt 37.

## Dependency installation

The project metadata remains authoritative in `pyproject.toml`. Prompt 37 adds
`requirements.lock` as a constraints/lock file for reproducible verification.

```bash
python -m pip install -e ".[test]" -c requirements.lock
```

The lock records the Linux verification dependency set and pins the existing
Windows-only `tzdata` dependency with a platform marker.

## Baseline inspection

Inspection is read-only:

```bash
python tools/verify_baseline.py inspect
```

It reports Git identity, canonical source identity, dependency declaration
identity, resolved lock identity, schema identities, and environment metadata.

## Baseline generation

Generation is explicit and writes the machine-readable baseline manifest:

```bash
python tools/verify_baseline.py generate \
  --parent-git-commit 7de2c58d24b1bd005405fa3a8e230b0749ace69c \
  --manifest release/baseline.json \
  --test-baseline-json '{"tests_collected":1110,"tests_passed":1110,"tests_failed":0,"tests_skipped":0,"warnings":0}'
```

The manifest is deterministic JSON with sorted keys and a trailing newline.
Release evidence under `release/` is excluded from canonical source identity to
avoid self-referential hashes.

## Baseline verification

Verification is read-only:

```bash
python tools/verify_baseline.py verify --manifest release/baseline.json
```

Verification checks:

- manifest schema support;
- Git ancestry from the Prompt 37 parent commit;
- canonical source-content identity;
- dependency declaration identity;
- resolved environment lock identity;
- configuration, state, and checkpoint schema identities.

Mismatch categories are machine-readable, for example:

```text
GIT_COMMIT_MISMATCH
SOURCE_CONTENT_MISMATCH
DEPENDENCY_DECLARATION_MISMATCH
RESOLVED_ENVIRONMENT_MISMATCH
CONFIG_SCHEMA_MISMATCH
STATE_SCHEMA_MISMATCH
CHECKPOINT_SCHEMA_MISMATCH
MANIFEST_SCHEMA_UNSUPPORTED
```

## Test execution

Focused Prompt 37 tests:

```bash
python -m pytest Tests/Unit/test_provenance_baseline.py
```

Checkpoint/recovery regression:

```bash
python -m pytest \
  Tests/Unit/test_persistence.py \
  Tests/Unit/test_recovery.py \
  Tests/Integration/test_persistence_recovery.py \
  Tests/Integration/test_runtime_recovery_epoch.py
```

Full regression:

```bash
python -m pytest
```

## Release creation

Create the source release archive explicitly:

```bash
python tools/verify_baseline.py archive \
  --archive-path release/artifacts/amrte-research-core-0.27.0-prompt37.zip
```

The archive contains the same canonical source material used for source
identity. It excludes mutable runtime state, logs, caches, virtual
environments, and release evidence. ZIP member timestamps are fixed to keep the
archive checksum deterministic.

## Release verification

After archive generation, record the archive SHA-256 in `release/baseline.json`
by regenerating the manifest with `--archive-path`, then run:

```bash
python tools/verify_baseline.py verify --manifest release/baseline.json
```

## Rollback reference

Source rollback to the pre-Prompt-37 baseline can be performed with normal Git
operations against:

```text
7de2c58d24b1bd005405fa3a8e230b0749ace69c
```

Example:

```bash
git checkout 7de2c58d24b1bd005405fa3a8e230b0749ace69c
```

This rolls back source files only. Persistent state and checkpoints under
runtime storage are separate operational artifacts and must be handled through
the checkpoint/recovery process. Source rollback must not be treated as
checkpoint rollback.

## Windows portability notes

Prompt 37 tooling uses `pathlib`, normalized POSIX-style relative paths for
identity, Python standard-library hashing/JSON/ZIP support, and Git subprocess
calls. It avoids hard-coded `/tmp`, `/home`, or local developer paths.

Native Windows Server/VPS qualification remains:

```text
NOT VERIFIED
```

## Known limitations

- A tracked manifest cannot contain the final Git commit that contains itself
  without a self-reference problem. The manifest records the Prompt 37 parent
  commit and verifies that the current commit descends from it. The final
  implementation commit is reported in the delivery report and Git history.
- The resolved dependency identity is based on `requirements.lock`; it is not a
  universal proof that every platform resolves identical transitive artifacts.
- The release archive is generated locally and ignored by Git as an artifact;
  its checksum is recorded in machine-readable release evidence.
- Prompt 37 performs static Windows portability review only.
