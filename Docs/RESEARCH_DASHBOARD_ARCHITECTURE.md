# Research Dashboard Architecture

AMRTE v0.24.8 adds a headless, framework-neutral dashboard composition layer for offline research monitoring. It consumes immutable upstream snapshots and Prompt 31 analytics without recalculating their authoritative values.

## Composition

`DashboardSnapshotAggregator` validates dataset, configuration, recovery epoch, and as-of compatibility before publishing an immutable `AMRTEDashboardSnapshot`. Missing, stale, future, or conflicting sources produce explicit partial, stale, unknown, or degraded states. Severe protection states dominate cosmetic health states.

The snapshot includes system status, data health, regime, research session, event metadata, active profile, strategy-health references, workflow/quality states, lifecycle counts, Prompt 28–30 protection, Prompt 31 performance, alerts, diagnostics, source identities, and deterministic fingerprints.

## Alerts

Dashboard alerts present upstream conditions; they do not recreate safety detection. Alert identity is deterministic and repeated conditions are grouped. Acknowledgement records that an operator saw an alert and never resolves the authoritative condition. Resolution can only be recorded from the source state.

## Governed controls

The control model is read-only by default. Supported neutral requests include pause/resume research evaluation, refresh, reconciliation/diagnostic requests, alert acknowledgement, research export, and UI preferences. Sensitive controls require permission, confirmation, reason, configuration lineage, and optimistic state-version checks. Duplicate requests are idempotent.

Resume is rejected unless the authoritative safety multiplier is fully permissive and dashboard status is healthy. There is no force-resume, safety override, circuit clearing, protection bypass, or permission-increase control.

## Persistence and recovery

Recovery preserves dashboard snapshots, alert acknowledgements, pause state, control results, and preferences. Schema/version/configuration/epoch and duplicate identities are validated. Incompatible recovery fails closed. Replay fingerprints enable deterministic restart verification.

## Presentation boundary

The repository has no established web/frontend framework, so v0.24.8 provides immutable page-ready DTOs and navigation data rather than introducing a competing UI stack. A later presentation adapter may render Overview, Analytics, Strategies, Lifecycles, Protection, Data Quality, Alerts, Diagnostics, Audit, and Configuration views without changing calculations.

## Safety boundary

This is not a broker or trading interface. It has no account, balance, equity, monetary P&L, position, order, fill, leverage, margin, live/demo trading, or financial execution capability. Visual design and actual interactive frontend implementation are not included.
