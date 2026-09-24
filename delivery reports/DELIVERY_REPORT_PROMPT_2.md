# AMRTE — Prompt 2 Delivery Report

**Prompt:** Master Configuration & Research Profiles Engine  
**Status:** PASS WITH DOCUMENTED SAFETY-SCOPE DEFERMENTS  
**Version:** 0.2.0

## Upstream inspection and gap scan

The complete Prompt 1 implementation was inspected first. Its type system,
snapshot foundation, lifecycle, health, capabilities, audit hooks, clocks,
identity, numerical safety, results/errors, and tests were reused.

Prompt 1 already had basic layered dictionaries and immutable values/provenance.
Prompt 2 required typed setting definitions, immutable profiles, comprehensive
validation, canonical hashing, richer snapshots, diffs, schema classification,
atomic switching, rollback, and readiness integration.

No accepted Prompt 1 component was replaced unnecessarily. Its 22-test baseline
passed before and after Prompt 2.

## Files created

- `src/amrte/core/config_schema.py`
- `src/amrte/core/profiles.py`
- `src/amrte/core/config_engine.py`
- `Tests/Unit/test_configuration_engine.py`
- `Tests/Integration/test_configuration_readiness.py`
- `Tests/Regression/test_prompt2_baseline.py`
- `Config/Profiles/profile_comparison.json`
- `DELIVERY_REPORT_PROMPT_2.md`

## Files modified

- `pyproject.toml`
- `README.md`
- `Docs/ARCHITECTURE.md`
- `src/amrte/app.py`
- `src/amrte/core/constants.py`
- `src/amrte/core/types.py`

## Typed configuration schema

`SettingDefinition` records key, type, unit, default, bounds, required status,
safety classification, override policy, choices, and deprecation replacement.

The implemented schema covers general/runtime controls, abstract research units,
fictional instruments, timeframe roles, quality/resource envelopes, deterministic
seeds, protection, logging, backtest metadata, optimization limits, fictional
simulation flags, and permanent execution restrictions.

## Profiles

- **CONSERVATIVE:** most restrictive standard fictional-research envelope.
- **BALANCED:** default fictional-research envelope.
- **AGGRESSIVE:** wider but bounded fictional-research envelope.
- **CUSTOM:** user values through the identical schema and validator.

Profiles are immutable data bundles, contain no executable logic, and cannot
alter hard safety. Their machine-readable differences are in
`Config/Profiles/profile_comparison.json`.

## Resolution and merge semantics

Precedence is global defaults → profile → custom/profile values → strategy-
labelled overrides → instrument-labelled overrides → runtime restrictions →
hard-safety proof.

Scalars, enums, and tuples replace inherited values. Lists normalize to tuples
for tuple fields. Maps merge shallowly only when both values are maps. Unknown
fields are retained for validation and never silently ignored.

## Validation and provenance

Implemented type, required, enum, finite-number, bound, fictional-instrument,
timeframe-order, research-unit, resource-ceiling, hard-safety, unknown-field,
secret-like-field, deprecation, and strict-mode validation.

Structured issues carry code, severity, path, message, current value,
constraint, and suggested correction. Snapshots retain the winning source and
overridden-source history for each changed setting.

## Snapshots, hashing, and schema versions

Snapshots contain ID, application/schema versions, profile, immutable values,
provenance, timestamp, SHA-256 configuration hash, validation status, warnings,
runtime, and override history.

Canonical serialization sorts mappings and normalizes enums/tuples. Equivalent
inputs generate the same fingerprint regardless of mapping order.

Schema classification supports `CURRENT`, `COMPATIBLE`, `MIGRATION_REQUIRED`,
`INCOMPATIBLE`, and `CORRUPTED`. A migration interface is prepared; no migration
is currently necessary.

## Atomic activation and rollback

Switching constructs and validates a complete candidate before activation. An
explicit deterministic safe boundary is required. Invalid candidates never
replace the active or last-valid snapshot. Activation, rejection, and rollback
are audited through Prompt 1's existing audit interface.

## Readiness integration

Startup now uses `MasterConfigurationProvider`. A valid snapshot must be built
and atomically activated before Prompt 1 can report `READY`.

## Tests

- **Total:** 67
- **Passed:** 67
- **Failed:** 0
- **Skipped:** 0
- **Prompt 1 regression:** 22 passed
- **Prompt 2 additions:** 45 passed

Coverage includes all profiles, custom configuration, precedence, provenance,
hard-safety attempts, numerical boundaries, NaN/infinity, timeframes, fictional
instruments, unknown/deprecated fields, schema states, immutability, deterministic
hashing, canonical serialization, diffs, activation, rollback, seed retention,
readiness, and source safety.

## Safety verification

- Fail-closed configuration activation: verified.
- Broker connectivity and authentication: absent.
- Real/demo execution: absent and non-configurable.
- Network dependencies: absent.
- Realistic leveraged-market simulation: absent.
- Price/fill/position lifecycle: absent.
- Martingale and unlimited exposure: permanently false.
- Protection, fail-closed, no-look-ahead, and audit controls: non-disableable.
- Only `FICTIONAL_*` identifiers are accepted as instruments.

## Safety-scope deferments

The following requested contracts were not implemented because together they
would create a realistic leveraged-market simulator:

- account capital/equity/margin models;
- financial risk and portfolio-exposure parameters;
- correlation, drawdown, and financial loss-limit parameters;
- fill, retry, spread, slippage, and partial-fill models;
- market-session and news-trading controls;
- strategy indicator and signal-tuning fields;
- stop, target, break-even, trailing, and position-management fields;
- realistic datasets or currency-pair configuration.

## Known issues and technical debt

- Prompt 1's original `LayeredConfigurationProvider` remains solely for backward
  compatibility and regression coverage. Runtime startup uses the Prompt 2
  master engine.
- State persistence remains in-memory as established by Prompt 1.
- Durable audit infrastructure remains deferred to Prompt 4.
- No known critical defect remains unresolved.

## Regression and readiness

**Regression status: PASS.** Prompt 2 is ready as the configuration baseline for
the next permitted roadmap prompt within the same safety boundary.

