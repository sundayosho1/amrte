# AMRTE — PROMPT 20 DELIVERY REPORT

**Prompt:** Profit-Taking & Research Exit Management Engine  
**Version:** 0.20.0  
**Phase:** Phase IV — Risk Management  
**Status:** ACCEPTED WITH DOCUMENTED LIMITATIONS — OFFLINE/FICTIONAL RESEARCH

## Baseline

- Upstream version: AMRTE v0.19.0
- Prompt 19 accepted: YES
- Regression baseline: 590 passed

## Architecture

- Exit engine: IMPLEMENTED (`ResearchExitManagementEngine`)
- ExitPolicy: IMPLEMENTED; strategy family/variant metadata, version and configuration lineage
- ResearchExitPlan / ResearchExitEvent: immutable and deterministic
- ResearchExitLedger: bounded, recoverable, idempotent event storage
- Prompt 21 handoff: immutable `ExitManagementState`

## Authority Boundaries

- Prompt 6 structure: consumed; not recalculated
- Prompt 9 time: UTC timestamps, session-end flag and `TradingDayID` consumed
- Prompt 19 invalidation: authoritative and precedence-preserving
- Prompt 17/18 exposure: final fictional exposure consumed
- Duplicate engines detected: NO

## Targets, Stages, Partials and Runner

- Fixed R: bullish/bearish and multi-R implemented using Prompt 19 distance
- Normalized research R: RESOLVED_NOW
- Financial realized R:R: DEFERRED_BY_SAFETY_SCOPE; not claimed
- Structural targets: point-in-time availability, direction and strategy/signal lineage validated
- TP1/TP2/TPn: generic bounded stages; maximum default 16
- Fractions: `[0,1]`; cumulative planned fractions plus runner cannot exceed 1
- Quantization: deterministic conservative floor to configured exposure step
- Runner: remaining exposure only; activates after target stages; Prompt 21 metadata supported
- Duplicate targets: merge, highest-priority or reject-ambiguous policy contract

## Strategy-Specific Exits

- S1: strategy profile metadata supports fixed-R and supplied structure
- S2 Immediate / Retest: separate strategy-variant identities; shared breakout lineage does not merge state
- S3: existing `MeanReversionDestination` can be supplied as structural evidence; range mean is not recalculated

## Time, Regime and Invalidation Exits

- Max bars: IMPLEMENTED using authoritative observation indexes
- Elapsed time: IMPLEMENTED using research timestamps
- Session end: IMPLEMENTED using Prompt 9-derived observation state
- Trading-day end: IMPLEMENTED by comparing stored and observed Prompt 9 `TradingDayID`
- Regime/state: restrictive full-exit behavior for incompatible, abnormal and unknown authoritative states
- Prompt 19 invalidation: terminates remaining exposure and outranks targets

## Same-Bar Ambiguity and Accounting

- Detection: target plus invalidation in one observation
- Default: `AMBIGUOUS_NO_RESULT`
- Higher-resolution resolution: supported when authoritative ordering is supplied
- Optimistic assumption: NO
- Exposure accounting: immutable before/reduced/after values; monotonic and bounded
- Completion: immutable completion record at zero remaining exposure

## Ledger, Recovery and Replay

- Bounded: YES
- Recovery: engine/configuration compatibility required
- Restart state: completed stages, remaining exposure, runner and events preserved
- Duplicate exit prevention: deterministic event identity and ledger deduplication
- Deterministic replay: PASS

## Observability and DecisionTrace

- Evaluation, plan creation, no-action, ambiguity and partial-exit events emitted through the existing audit abstraction
- Plan trace links strategy decision, invalidation, target evidence, stage construction and eligibility
- Event/accounting evidence is recorded in immutable events and ledger state

## Prompt 19 Gap Review

| Issue | Classification | Prompt 20 impact |
|---|---|---|
| S2 retest tolerance refinement | TECHNICAL_DEBT | Non-blocking; exit engine consumes accepted S2 evidence |
| Advanced multi-observation aggregation | TECHNICAL_DEBT | Multi-close/structural confirmation are contracts; generic evaluator expects already-authoritative confirmation |

## Pending Issues

| Item | Classification | Future owner |
|---|---|---|
| Target-selection priority beyond stage-declared targets | PARTIALLY_IMPLEMENTED | Prompt 20 extension |
| Rich target-conflict diagnostics | PARTIALLY_IMPLEMENTED | Prompt 20 extension |
| Lower-timeframe lineage validation inside ordering resolver | PARTIALLY_IMPLEMENTED | Prompt 20 extension |
| Data-failure freeze/unresolved continuation workflow | PARTIALLY_IMPLEMENTED | Prompt 20 extension |
| S2 retest tolerance | TECHNICAL_DEBT | S2 strategy owner |
| Candidate timeframe-conflict detail | TECHNICAL_DEBT | Strategy/intelligence owners |
| Native Windows runtime testing | NOT_IMPLEMENTED | Deployment validation |
| Offline calendar coverage / volume availability | OUT_OF_SCOPE | Dataset owners |
| Financial realized R:R | DEFERRED_BY_SAFETY_SCOPE | Future offline execution analytics only |
| Correlation / portfolio risk / protection | DEFERRED_BY_DESIGN | Later phases |
| Break-even and trailing | DEFERRED_BY_DESIGN | Prompt 21 |

None of the documented limitations weakens invalidation precedence, exposure monotonicity, temporal safety, or the non-execution boundary. Prompt 21 may proceed against the immutable handoff but must not depend on the partial advanced-resolution features.

## Performance

- Instruments: 1 fictional fixture
- Hypotheses / plans: 200
- Target candidates / stages: 200 / 200
- Cache/plans/targets bounded at 64; ledger bounded at 128
- Performance test duration including test startup: 0.340375 seconds
- Peak child RSS: 33,648 KiB
- Production-scale claim: NO

## Windows

- Static portability: PASS; OS-neutral code, no shell/runtime dependency in AMRTE, no absolute paths
- Native verification: NO

## Testing

- Prompt 20 focused: 27 passed
- Prompt 1–19 regression: 590 passed
- Total: 617 passed
- Failed: 0
- Skipped: 0
- Full-suite duration: 17.25 seconds
- Compilation: PASS
- Temporal, invariant, metamorphic, failure-injection, ambiguity, accounting, recovery and isolation behavior: covered in focused tests, with advanced gaps disclosed above

## Safety Scan and Verification

Status: PASS. Source scan found no broker, account, live-feed, live-P&L, order, leverage, margin, break-even, trailing, or real/demo execution implementation. Matches occurred only in denial tests, hard-safety configuration, and ordinary classification-margin terminology.

Confirmed: no broker connectivity/authentication/account access; no broker TP/SL; no partial broker closure; no position closure/order modification/live fills; no leverage/margin; no break-even/trailing; no future leakage; no optimistic same-bar assumption; no exposure creation through exits.

## Gap Scan

- Implemented: authoritative exit engine; fixed-R and supplied structural targets; generic stages; partials; runner; time/regime/invalidation exits; ambiguity handling; accounting; ledger; recovery; observability; trace; Prompt 21 handoff
- Partial: advanced target arbitration/conflict diagnostics, internal lower-timeframe lineage resolver, condition-specific multi-observation aggregation, frozen-data continuation workflow
- Deferred by design: Prompt 21 protective-boundary evolution, portfolio/correlation/protection
- Deferred by safety scope: broker-realized financial R:R and every broker/account/execution capability
- Technical debt: Prompt 19 S2 tolerance, advanced aggregation, richer timeframe conflict detail
- Not implemented: native Windows runtime verification
- Blocked: none for core Prompt 20 acceptance; advanced optional policies remain unavailable

## Known Limitations

The engine models research destinations and exposure reduction, not executable orders or fills. Structural candidates are consumed through the Prompt 20 evidence adapter because Prompt 6 does not expose one universal target API. Higher-resolution ordering is accepted as authoritative input rather than discovered internally. `MULTI_CLOSE`, structural-confirmation and strategy-defined trigger policies require upstream-confirmed evidence for advanced aggregation.

## Package Integrity

- Archive: `AMRTE_Prompt_20_v0.20.0.zip`
- SHA-256: `e7768b23212f56c4570d7843e2f14f0d8b235afd33895f8b314b903e1eeef3df`

## Overall Acceptance

**ACCEPTED WITH DOCUMENTED LIMITATIONS**

## Ready for Prompt 21

**YES — after review and acceptance of this report.**
