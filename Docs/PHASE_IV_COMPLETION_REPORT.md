# AMRTE — PHASE IV RISK MANAGEMENT COMPLETION REPORT

**Phase:** Phase IV — Risk Management  
**Version:** 0.21.0

## Prompt Status

- Prompt 17 — Per-Hypothesis Research Risk & Sizing: ACCEPTED
- Prompt 18 — Adaptive Risk: ACCEPTED
- Prompt 19 — Thesis Invalidation: ACCEPTED
- Prompt 20 — Profit-Taking & Exit Management: ACCEPTED WITH DOCUMENTED LIMITATIONS
- Prompt 21 — Break-Even & Trailing Protection: ACCEPTED WITH DOCUMENTED LIMITATIONS

## Master Gate

| Gate | Result |
|---|---|
| Risk pipeline | PASS |
| Authoritative invalidation | PASS |
| Normalized distance / single 1R definition | PASS |
| Base sizing | PASS |
| Adaptive restriction | PASS |
| Exit management | PASS |
| Break-even | PASS |
| ATR / structure / R trailing | PASS |
| Exposure monotonicity | PASS |
| Protective-boundary monotonicity | PASS |
| Temporal integrity | PASS |
| Conservative same-bar protection | PASS |
| Recovery | PASS |
| Deterministic replay | PASS |
| Observability / DecisionTrace | PASS |
| Static Windows portability | PASS |
| Native Windows | NOT TESTED |
| Research-only safety | PASS |

## Verified Phase IV Invariants

- Positive fictional exposure requires authoritative invalidation.
- Final risk does not exceed adaptive risk, which does not exceed base risk.
- Prompt 20 and Prompt 21 cannot increase or restore exposure.
- Protective boundaries cannot loosen and reduced risk cannot re-expand.
- Future evidence cannot rewrite risk, exit, or protection history.
- A same-bar future-derived boundary cannot act earlier within that bar.

## Cross-Engine Scenarios

The integration suite verifies the authoritative chain through invalidation, sizing/adaptive restriction, partial exit, runner activation, break-even, R trailing, protective termination, same-bar conservatism, restart, and deterministic replay. Strategy and variant metadata remain isolated; Prompt 21 does not recreate S1/S2/S3 rules.

## Cumulative Verification

- Total: 641 passed
- Failed: 0
- Skipped: 0
- Compilation: PASS
- Full-suite duration: 17.58 seconds

## Known Limitations and Pending Issues

- Internal authoritative lower-timeframe event-order resolution remains technical debt.
- Multi-close and structural-confirmation aggregation require authoritative history.
- Detailed protective noise-zone policies and rich data-freeze continuation are incomplete.
- S2 retest tolerance and candidate timeframe diagnostics carry forward.
- Financial realized R:R, correlation, portfolio risk, and broker-realized costs remain unavailable.
- Native Windows runtime verification has not been performed.

These limitations do not weaken the conservative monotonicity, no-look-ahead, exposure, or non-execution invariants.

## Phase IV Acceptance

**ACCEPTED WITH DOCUMENTED LIMITATIONS**

## Ready for Phase V

**YES — after report review and acceptance. Phase V must consume authoritative Phase IV artifacts and preserve all restrictions.**
