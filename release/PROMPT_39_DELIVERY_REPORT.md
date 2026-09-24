# AMRTE PROMPT 39 - CANONICAL MARKET DATA CONTRACT & SOURCE ADAPTER FRAMEWORK DELIVERY REPORT

## A. Result

```text
ACCEPTED WITH LIMITATIONS
```

Prompt 39 establishes a canonical finalized-bar market data boundary, source
adapter framework, dataset authority, point-in-time replay contract, runtime
composition registration, read-only API diagnostics, tests, and release
evidence. Limitations are explicit: no live source connector is configured and
no research/strategy/execution pipeline is activated.

## B. Starting Baseline

```text
Application Version:     0.27.0
Package:                 amrte-research-core
Parent Prompt:           Prompt 38 accepted runtime composition baseline
Parent Git Commit:       e4969624ca88bf84ca794f3d539ff14f9a28801a
Parent Source SHA-256:   22c6b1c33425ac0f1da6ab119e4f78aff7bb25d7c0eb3f70790d1d0612ec1a4c
Parent Tests:            1,168 passed / 0 failed / 0 skipped
```

## C. Git State

```text
Working Branch:          cursor/prompt-39-market-data-contract-b31e
Implementation Commit:   7a038d78c0425bb12e5d4c3058c9df62ab44f8d8
Base Branch:             cursor/prompt-38-runtime-composition-b31e
Working Tree:            Prompt 39 evidence files added after implementation commit
```

## D. Pre-Implementation Tests

```text
Collected:    1,168
Passed:       1,168
Failed:       0
Skipped:      0
Duration:     13.66s
Environment:  Linux-6.12.94+-x86_64-with-glibc2.39 / CPython 3.12.3
```

## E. Existing Architecture Reuse

Prompt 39 reuses the existing `RuntimeComposition` authority from Prompt 38,
the existing `NormalizedBar`, `InstrumentMetadata`, `DataProvenance`,
`DeterministicMarketDataProvider`, and `MarketDataService` concepts, and the
existing read-only FastAPI diagnostic style. It does not introduce a second
runtime, registry, execution provider, or pipeline controller.

## F. Reuse Classification

```text
NormalizedBar:                    ADAPTED for compatibility
InstrumentMetadata:               ADAPTED via InstrumentIdentity
DeterministicMarketDataProvider:  REUSED as existing offline provider concept
MarketDataService:                PRESERVED; canonical adapters bridge to/from it
Dataset fingerprinting:           REUSED concept with canonical observation hashes
RuntimeComposition:               AUTHORITATIVE composition surface
Research pipeline:                LEFT INACTIVE / UNAVAILABLE
```

## G. Canonical Observation Contract

Prompt 39 adds `CanonicalMarketObservation` in
`src/amrte/market/observation.py`. The contract is provider-neutral and
supports finalized bar observations only.

```text
Observation Schema Version:  1.0
Observation Schema Identity: efc145adc2e2eb8895ac06c348e26a0d6ac11f1f0c2acb4f1f6042b61dbcf84d
Observation Type:            BAR
Temporal Semantics:          BAR_CLOSE
```

## H. Instrument and Source Identity

`InstrumentIdentity` separates canonical IDs from source symbols and carries
asset-class, precision, volume semantics, session reference, and aliases.
`SourceIdentity` records source ID, adapter type/version, source dataset, and
source version so provenance does not depend on provider-specific object types.

## I. Temporal Semantics

Canonical observations use closed-bar semantics:

```text
period_start < event_time <= available_at <= received_at
event_time == bar close / period end
replay availability uses available_at <= logical_time
```

Naive timestamps are rejected; aware timestamps are canonicalized to UTC.

## J. Numeric and OHLC Validation

Canonical numeric values are parsed as `Decimal` for deterministic content
identity. Validation rejects NaN, infinity, non-positive OHLC values, negative
volume, `high < max(open, close)`, `low > min(open, close)`, and `high < low`.

## K. Observation Provenance

Each observation carries `ObservationProvenance` with source locator, optional
source path, raw-record fingerprint, transformation names, and raw retention
policy. CSV imports retain raw-record fingerprints without requiring raw
payload retention.

## L. Source Adapter Framework

Prompt 39 adds `CSVBarSourceAdapter`, a deterministic UTF-8 CSV adapter for
finalized bars. Required columns:

```text
instrument,timeframe,period_start,period_end,available_at,received_at,open,high,low,close
```

Optional columns:

```text
volume,volume_kind,sequence
```

Row-level diagnostics report missing fields, unknown instruments, invalid
timestamps, invalid numbers, invalid OHLC, and adapter errors.

## M. Dataset Authority

`build_canonical_dataset(...)` validates observations, deduplicates exact
duplicates, rejects revised/colliding identities, detects out-of-order source
records, detects sequence regressions, warns on sequence gaps, and produces a
canonical dataset manifest.

## N. Dataset Manifest

```text
Dataset Manifest Schema Version:  1.0
Dataset Manifest Schema Identity: 0412d47d673c75345e5b9604a213e7889567878a592cc1f443805cbacd0b44f3
```

The manifest records dataset ID, dataset fingerprint, observation schema
version, sources, adapter versions, instruments, timeframes, temporal range,
observation count, and validation summary.

## O. Deterministic Identity

Observation IDs are derived from source, instrument, observation type,
timeframe, event time, and sequence. Observation fingerprints are SHA-256 over
canonical JSON excluding the fingerprint itself. Dataset fingerprints are
derived from ordered observation fingerprints and schema identity.

## P. Point-In-Time Replay

`CanonicalDatasetReplay.available_as_of(logical_time)` returns only
observations whose `available_at` timestamp is not after the logical time. This
guards against look-ahead at replay selection time.

## Q. Look-Ahead Safety

Look-ahead safety is enforced in both creation/validation and replay:

```text
create_canonical_bar(..., logical_time=...) rejects future availability
validate_canonical_observation(..., logical_time=...) reports future availability
CanonicalDatasetReplay filters by available_at <= logical_time
```

## R. Compatibility Adapters

Prompt 39 adds:

```text
observation_from_normalized_bar(...)
observation_to_normalized_bar(...)
```

These preserve compatibility with existing market-data tests and services while
requiring finalized `CLOSED_BAR` inputs for canonical observations.

## S. Runtime Composition Integration

Prompt 39 registers these components with the existing `RuntimeComposition`:

```text
market_data_contract
market_data_source_adapter_framework
market_dataset_authority
market_data_configured_dataset
```

The first three are required and active with the core runtime. The configured
dataset slot is optional and intentionally `UNAVAILABLE` until a dataset is
explicitly loaded.

## T. Pipeline Activation Status

```text
Observation -> Intelligence -> Strategy -> Decision:
NOT ACTIVATED BY PROMPT 39
```

The Prompt 38 `research_pipeline` marker remains registered, inactive, and
unavailable.

## U. Financial Execution Boundary

```text
Execution:            PROHIBITED
Broker Connectivity:  UNAVAILABLE
Live Trading:         UNAVAILABLE
Demo Trading:         UNAVAILABLE
```

Prompt 39 does not add execution capabilities, broker APIs, order routing,
position management, portfolio activation, risk execution, or protection
execution.

## V. API Surface

Prompt 39 adds a read-only endpoint:

```text
GET /api/v1/market-data-boundary
```

It exposes schema versions/identities, component status, adapter framework
status, dataset authority status, validation policy, replay policy, research
pipeline status, and financial execution boundary.

## W. Dataset Replay Projection

`GET /api/v1/dataset-replay` now includes
`canonical_market_data_boundary` and reports canonical contract, adapter
framework, dataset manifest, and point-in-time market replay capabilities as
runtime-authoritative when their composition components are ready.

## X. Audit and Observability

Prompt 39 boundary components emit `market_data_boundary_initialized` through
the existing audit/observability path. Existing composition events continue to
record component registration, validation, initialization, readiness, and
activation.

## Y. Persistence and Recovery

Prompt 39 components are not persistence or recovery participants. Dataset
manifests are immutable evidence artifacts; future persisted dataset loading
can be added without changing the execution boundary.

## Z. Configuration Impact

No configuration schema changes were required. Existing offline market-data
configuration remains intact.

## AA. Dependency Impact

No third-party dependencies were added. Prompt 39 uses the Python standard
library and existing AMRTE modules.

## AB. Test Coverage Added

```text
Tests/Unit/test_market_observation_contract.py
Tests/Integration/test_market_data_boundary_api.py
Tests/Performance/test_prompt39_market_dataset_load.py
```

Existing runtime composition tests were updated to include Prompt 39 inventory
entries.

## AC. Focused Regression

```text
Command:
  python -m pytest Tests/Unit/test_market_observation_contract.py \
    Tests/Integration/test_market_data_boundary_api.py \
    Tests/Performance/test_prompt39_market_dataset_load.py \
    Tests/Unit/test_runtime_composition.py \
    Tests/Integration/test_runtime_composition_api.py \
    Tests/Unit/test_market_data.py \
    Tests/Integration/test_market_data_integration.py

Result:
  84 passed in 1.13s
```

## AD. Full Regression

```text
Command:      python -m pytest
Collected:    1,187
Passed:       1,187
Failed:       0
Skipped:      0
Warnings:     0
Duration:     14.82s
Environment:  Linux-6.12.94+-x86_64-with-glibc2.39 / CPython 3.12.3
```

## AE. Provenance Evidence

Prompt 39 evidence was generated under:

```text
release/prompt39/baseline.json
release/prompt39/data_contract.json
release/artifacts/amrte-research-core-0.27.0-prompt39.zip
```

Prompt 37 and Prompt 38 evidence files were preserved.

## AF. Prompt 39 Baseline Manifest

```text
Source SHA-256:       7a9e04fdef07c31df507fc2753ae24eeda0040367e81a440e7bf29dac555a1fe
Source File Count:    354
Archive SHA-256:      d5e7b97ac697091d7126038c7f0b8f4f40b2942dbd9394a547150990ad42d474
Archive File Count:   354
Dependency SHA-256:   6816de3b03f12084bf85bdc927075c7df8c37b41e16a3b1a6b75bbe36b67cfb9
Environment Identity: c040b7b8c149049bc2ffaa4cabed01e548b4b3b49d339debc715fc0f02a25539
```

## AG. Manifest Verification

```text
Command: python tools/verify_baseline.py verify --manifest release/prompt39/baseline.json
Result:  PASSED
Mismatches: []
```

## AH. Historical Evidence Preservation

Prompt 37 and Prompt 38 manifests remain in place as historical release
evidence. Prompt 39 adds a new `release/prompt39/` evidence set rather than
rewriting prior prompt evidence.

## AI. Security and Safety Notes

The implementation performs no network fetch, broker login, order submission,
portfolio mutation, risk action, or protection action. CSV adapter diagnostics
record fingerprints and locators, not secrets.

## AJ. Performance Notes

The added performance test builds and replays a 5,000-observation canonical
dataset within the existing bounded test threshold.

## AK. Limitations

```text
Configured canonical dataset:     NOT LOADED
Live source adapter:              NOT CONFIGURED
Native Windows qualification:     NOT VERIFIED
Research pipeline activation:     NOT PERFORMED
Financial execution capability:   PROHIBITED
```

## AL. Files Added

```text
src/amrte/market/observation.py
src/amrte/market/boundary.py
src/amrte/web/market_data_boundary.py
Tests/Unit/test_market_observation_contract.py
Tests/Integration/test_market_data_boundary_api.py
Tests/Performance/test_prompt39_market_dataset_load.py
release/prompt39/baseline.json
release/prompt39/data_contract.json
release/PROMPT_39_DELIVERY_REPORT.md
```

## AM. Files Modified

```text
src/amrte/core/composition.py
src/amrte/web/app.py
src/amrte/web/dataset_replay.py
Tests/Unit/test_runtime_composition.py
Tests/Integration/test_runtime_composition_api.py
```

## AN. Acceptance Summary

Prompt 39 satisfies the requested canonical market data boundary by providing
provider-neutral observation identity, strict validation, deterministic
fingerprints, dataset manifests, source adapter diagnostics, replay
look-ahead controls, composition visibility, API evidence, and regression
coverage while preserving Prompt 38 runtime authority.

## AO. Final Status

```text
Implementation:          COMPLETE
Focused Tests:           PASSED
Full Regression:         PASSED
Prompt 39 Manifest:      PASSED
Financial Boundary:      PROHIBITED
Research Pipeline:       NOT ACTIVE
Ready for Review:        YES, WITH LIMITATIONS LISTED ABOVE
```
