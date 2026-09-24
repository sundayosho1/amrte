# AMRTE Features and Functions Guide — Neutral Research Build

This catalogue describes the accepted AMRTE architecture as a non-financial,
offline research and generic workflow system. Historical modules with
market-oriented names remain research abstractions and cannot connect to an
account, submit instructions, or execute financial activity.

| Area | Purpose | Inputs | Outputs | Failure behavior | Operator action |
|---|---|---|---|---|---|
| Core | Identity, configuration, state, recovery | Versioned configuration | Immutable state and IDs | Fail closed | Validate configuration and reconcile |
| Observability | Audit, logs, traces | Component events | Correlated evidence | Mark degraded/restricted | Inspect reason code and trace |
| Offline data | Validate approved fixtures | Historical/synthetic files | Immutable snapshots | Reject stale/invalid evidence | Repair or replace dataset |
| Intelligence | Derive research context | Valid snapshots | Research-only context | No positive inference | Inspect upstream health |
| Strategy research | Produce hypothetical candidates | Intelligence snapshots | Non-executable artifacts | NO_ACTION | Review evidence only |
| Risk research | Dimensionless constraint studies | Research artifacts | Restriction metadata | Restrict/block | Correct upstream evidence |
| Workflow simulation | Exercise state machines | Authorized neutral work | Completion events | Fail closed/reconcile | Restore checkpoint |
| Analytics | Descriptive offline metrics | Immutable outcomes | Reports | Mark insufficient | Improve evidence quality |
| Validation | Experiment and robustness studies | Offline observations | Reproducible evidence | Preserve negative results | Review gaps and contamination |
| Forward operations | Long-running neutral shadow workflow | New neutral observations | Health/drift metadata | Pause/restrict | Resolve protection state |
| Deployment diagnostics | Health tree, alerts, diagnostics, update safety | Runtime metadata | Operator reports | Never report false healthy | Follow recovery action |

All modules inherit these permanent limitations: no broker or account
connectivity, no credential collection for financial services, no orders,
positions, leverage, margin, wagering, live/demo trading, or financial execution.

