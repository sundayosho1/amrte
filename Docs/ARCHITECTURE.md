# Prompt 1 Architecture

## Dependency direction

Application orchestration depends on core domain services. Core services depend
on interfaces. Local infrastructure implements those interfaces. Infrastructure
does not call back into application orchestration.

## Ownership

- **Core** owns shared types, configuration, lifecycle, state, health,
  capabilities, versioning, identity, numerical validation, and interfaces.
- **Infrastructure** owns local in-memory repositories, deterministic random
  implementation, audit collection, and the prohibited-operation execution stub.
- **Market, Strategies, Risk, Portfolio, Protection, Analytics, UI, and
  Simulation** remain intentionally unimplemented for later prompts.

## Safety boundary

There is no network dependency, broker SDK, authentication model, account login,
real/demo adapter, live price provider, order representation, fill model, or
position lifecycle. `IExecutionProvider` exists only to preserve dependency
inversion; its sole implementation rejects every request with
`CAPABILITY_NOT_AVAILABLE` and records the attempt.

Research tests use fictional identifiers only. Currency-pair datasets and
realistic leveraged-market simulation are deferred outside this build.

## Lifecycle

Initialization detects a permitted runtime, resolves mandatory services, loads
an immutable configuration snapshot, loads state, evaluates readiness, and only
then enters `READY`. Failures enter `ERROR`. `READY` and `RUNNING` are separate.
Shutdown persists state, records the reason, flushes audit output, and enters
`STOPPED`.

## Configuration

Precedence is global, profile, strategy, instrument, then runtime. Hard-safety
keys are applied last and cannot be weakened. Each effective value records its
provenance.

### Prompt 2 configuration engine

`MasterConfigurationEngine` is the authoritative owner of active runtime
configuration. It materializes defaults and profile deltas, applies approved
override layers, validates field/cross-field/safety rules, and emits an
immutable `EffectiveConfigurationSnapshot`.

Snapshots include deterministic IDs and hashes, application/schema versions,
profile, runtime, timestamp, warnings, winning provenance, and overridden
sources. Equivalent input produces equivalent canonical serialization and hash.

Activation is atomic and requires an explicit safe boundary. Invalid candidates
never replace the last valid snapshot. Hot reload is explicitly unavailable.
The schema migration interface is prepared, but no migration is currently
required.

Profiles are immutable data bundles. They adjust only abstract quality,
concurrency, and fictional resource-load boundaries. No hidden profile branches
exist in application logic.

Market-account, financial-risk, spread, slippage, stop, exit, and realistic
execution settings are intentionally absent. Execution remains permanently
unavailable.
