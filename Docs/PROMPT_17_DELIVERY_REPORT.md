# AMRTE — PROMPT 17 DELIVERY REPORT

**Prompt:** Per-Hypothesis Risk Budget & Simulated Exposure Sizing Engine  
**Version:** 0.17.0  
**Phase:** Phase IV — Risk Management  
**Status:** ACCEPTED FOR OFFLINE FICTIONAL RESEARCH

## Baseline

- Upstream: accepted AMRTE v0.16.0.
- Phase III gate: PASS.
- Regression baseline: 518 tests passed.

## Architecture

- Module: `amrte.risk.sizing`.
- Entry point: authoritative Prompt 16 `StrategyDecisionSnapshot` only.
- Output: immutable `RiskBudget`, `SimulatedExposureDecision`, and DecisionTrace.
- Domain: fictional capital, normalized distance, normalized risk units, and simulated exposure units only.

## Prompt 16 Integration

- SINGLE_PREFERRED: potentially eligible.
- MULTIPLE_COMPATIBLE: blocked by the conservative default; shared-budget contract exists but no portfolio allocator is implemented.
- NO_ACTION/ALL_REJECTED: zero exposure.
- BLOCKED/INCOMPLETE/UNKNOWN: fail closed.
- Upstream restrictions propagate monotonically.

## Research Capital

- Immutable `ResearchCapitalContext` with deterministic identity, as-of time, source and configuration lineage.
- Allowed sources: configured research capital, backtest research ledger, fictional simulation ledger and synthetic test fixture.
- No account or broker source exists.

## Base Risk and RiskBudget

- Base fraction is configuration-driven; no universal percentage is asserted.
- Base and effective fictional risk are distinct.
- Effective risk can never exceed base risk.
- Restrictive modifiers compose by MIN by default, with an optional multiplicative policy; every modifier must be within [0,1].
- Zero fictional risk is valid.

## Invalidation Distance Review

- `InvalidationDistanceContext` is immutable, point-in-time and normalized.
- Zero, negative, near-zero, excessive, missing, invalid and future distance fail closed.
- S1/S2/S3 do not currently expose one common authoritative normalized invalidation distance.
- Resolution: no hidden conversion was added. Synthetic/configured offline evidence is supported; missing strategy-authoritative evidence returns zero exposure.
- Future authoritative owner: Prompt 19 thesis-invalidation research geometry or a narrowly approved strategy contract extension.
- Executable stop created: NO.

## Cost Buffer

- Immutable normalized `ResearchCostBuffer` abstraction.
- Sources are configured, historical research, synthetic fixture or none.
- Missing policy supports BLOCK, configured conservative fallback, or NOT_REQUIRED.
- Missing mandatory cost never silently becomes zero.

## Simulated Exposure

- Raw exposure uses dimensionless fictional research units.
- Configurable minimum, maximum and step constraints.
- Maximum caps downward.
- Quantization uses Decimal `ROUND_FLOOR`.
- Below-minimum results return zero exposure rather than rounding upward.
- No mapping to lots, contracts, currency, ticks, pips or broker volume.

## Post-Quantization Validation

- Recalculated normalized risk includes the research cost buffer.
- Recalculated risk must not exceed the effective authorized budget plus explicit Decimal tolerance.
- Any overrun fails closed.

## Numerical Safety

- Decimal precision and tolerance are configured.
- NaN, infinity, negative capital, negative cost, invalid fraction, invalid distance, and invalid/zero step are rejected.
- Division by zero is impossible in the eligible path.

## Multiple Compatible Strategies

- Default: restricted/NO_ACTION.
- The engine never grants the full budget independently to several hypotheses.
- Cross-instrument and portfolio allocation remain outside Prompt 17.

## Health, Eligibility and Restrictions

- Health: healthy, degraded, restricted, insufficient-data, blocked, invalid and unknown.
- Eligibility: eligible, eligible-with-restrictions, not-eligible, blocked, incomplete and unknown.
- Errors and hard blocks always produce zero exposure.

## Recovery, Determinism and Cache

- Recovery validates engine and configuration identity.
- Budget, decision and cache histories are bounded.
- Cache identity includes Phase III snapshot, capital, invalidation, cost, modifiers, configuration and engine version.
- Identical inputs reproduce identical results and IDs.

## Observability and DecisionTrace

- Sizing start, completion and NO_ACTION are observable.
- Trace records the Phase III gate and Decimal risk-mathematics/invariant gate.
- Every decision identifies its upstream snapshot, capital context, distance, cost assumptions, configuration and recovery epoch.

## Temporal Integrity

- Future capital, invalidation, cost and modifier evidence cannot participate.
- Later capital/configuration/evidence creates a new deterministic decision and cannot rewrite history.

## Performance

- Dedicated bounded fixture: 200 evaluations.
- Budget, decision and cache history: capped at 64 entries.
- Focused suite: 19 tests in 1.826 seconds including process startup.
- Peak subprocess RSS: 34,168 KiB; traced allocation remained below 20 MB.
- Production-scale performance is not claimed.

## Windows

- Static portability: PASS.
- Native Windows tested: NO.
- Runtime has no shell, GUI, network or platform-specific path dependency.

## Safety-Scope Deferments

DEFERRED_BY_SAFETY_SCOPE: broker lot sizing, tick/pip values, contract sizes, real currency conversion, account equity, margin, leverage, broker symbol metadata, real/demo orders, executable stops/targets/exits and all live connectivity.

## Pending Issues

- Strategy-authoritative common normalized invalidation distance: upstream gap; conservative fixtures only at v0.17.0.
- Shared-budget allocation for multiple compatible hypotheses: Prompt 22/portfolio owner.
- Adaptive reductions and drawdown policy: Prompt 18.
- Native Windows verification: platform QA.
- Prompt 15 point-in-time distance technical debt remains relevant.

## Testing

- Prompt 17 focused: 19 passed, 0 failed, 0 skipped.
- Full Prompt 1–17 cumulative regression: 537 passed, 0 failed, 0 skipped.
- Compilation: PASS.
- Invariants include effective≤base, quantized≤raw/cap, recalculated≤authorized, modifiers≤1, hard-block→zero, and no future input.

## Safety Scan

PASS. No broker SDK, authentication, account, live-feed, lot, tick/pip, contract, margin, leverage, order, or executable position-management implementation was found in the Prompt 17 module.

## Gap Scan

| Requirement | Classification | Impact / future owner / blocking |
|---|---|---|
| Phase III authority and outcome gates | IMPLEMENTED | None |
| Fictional capital, base/effective budget and Decimal safety | IMPLEMENTED | None |
| Normalized invalidation contract and distance guards | IMPLEMENTED | None |
| Cost buffer and missing-cost policies | IMPLEMENTED | None |
| Raw exposure, constraints, floor quantization and recalculation | IMPLEMENTED | None |
| Health, eligibility, provenance, trace, recovery and cache | IMPLEMENTED | None |
| Shared-budget MULTIPLE_COMPATIBLE allocation | PARTIALLY_IMPLEMENTED | Default safe block; Prompt 22; does not block Prompt 17 or 18 |
| Strategy-derived normalized invalidation distance | PARTIALLY_IMPLEMENTED | Contract/consumption exist but S1–S3 lack common authoritative evidence; Prompt 19/upstream strategy owner; limits nonfixture sizing but fails closed |
| Adaptive risk | DEFERRED_BY_DESIGN | Prompt 18 |
| Portfolio/correlation | DEFERRED_BY_DESIGN | Prompt 22/Phase V |
| Broker-ready sizing and execution | DEFERRED_BY_SAFETY_SCOPE | Prohibited; never a Prompt 17 owner |
| Native Windows runtime | NOT_IMPLEMENTED | Platform QA; non-blocking |

## Known Limitations

Positive simulated exposure currently requires an explicitly supplied offline normalized invalidation context. AMRTE does not infer this from S1/S2/S3 or convert it into an executable stop. The default for multiple compatible hypotheses remains zero exposure.

## Package Integrity

- Archive: `AMRTE_Prompt_17_v0.17.0.zip`.
- SHA-256: see companion checksum file.

## Overall Acceptance

**ACCEPTED for offline fictional research architecture.**

## Ready for Prompt 18

**YES — after user review.** Prompt 18 may only reduce or block the established fictional base risk and must not add broker/execution capability.
