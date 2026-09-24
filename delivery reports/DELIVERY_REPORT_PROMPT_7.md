# AMRTE — PROMPT 7 DELIVERY REPORT

**Prompt:** Technical Indicator & Feature Engine  
**Version:** 0.7.0  
**Status:** PASS WITH SAFETY-SCOPE DEFERMENTS  
**Overall Acceptance:** ACCEPTED  
**Ready for Prompt 8:** YES, after user review

## Upstream Baseline

- AMRTE entering version: 0.6.0
- Prompt 1–6 regression: PASS
- Architecture conflicts: none. Prompt 5 remains the only price source and
  Prompt 6 lineage is referenced rather than recalculated.

## Files Created

- `src/amrte/market/features.py`
- `Tests/Unit/test_features.py`
- `Tests/Integration/test_features_integration.py`
- `Tests/Performance/test_features_load.py`
- `Tests/Regression/test_prompt7_baseline.py`
- `Docs/FEATURES.md`
- `DELIVERY_REPORT_PROMPT_7.md`

## Files Modified

- `src/amrte/market/__init__.py`
- `src/amrte/core/config_schema.py`
- `src/amrte/core/config_engine.py`
- `src/amrte/core/constants.py`
- `Tests/Regression/test_prompt6_baseline.py`
- `pyproject.toml`
- `README.md`

## Feature Architecture

| Area | Status | Definition/result |
|---|---|---|
| Input integration | IMPLEMENTED | Trusted synchronized Prompt 5 snapshots only. |
| Price sources | IMPLEMENTED | Open/high/low/close/median/typical/weighted close. |
| Bar state and shift | IMPLEMENTED | Explicit eligible-bar semantics. |
| Warm-up/value contract | IMPLEMENTED | Required/available observations and explicit health. |
| EMA | IMPLEMENTED | First N SMA seed, then `2/(N+1)` recursion. |
| ATR | IMPLEMENTED | Authoritative True Range and Wilder smoothing. |
| ADX/+DI/-DI | IMPLEMENTED | Wilder directional movement chain. |
| RSI | IMPLEMENTED | Wilder smoothing with no-gain/no-loss/flat safeguards. |
| MACD | IMPLEMENTED | Main, signal, histogram and histogram slope. |
| Bollinger | IMPLEMENTED | Population variance, bands, bandwidth, percent-B and deviation. |
| Candle features | IMPLEMENTED | Range, body, wicks, ratios and direction. |
| Returns/momentum | IMPLEMENTED | Named simple/log returns, ROC and displacement. |
| Moving averages | IMPLEMENTED | Separation, slope and price distance. |
| Volatility | IMPLEMENTED | Non-annualized realized volatility, percentile and expansion ratio. |
| Range/ATR features | IMPLEMENTED | Raw, percent-price and ATR-relative measurements. |
| Numerical safety | IMPLEMENTED | Non-finite and invalid division never become valid values. |
| Dependency graph | IMPLEMENTED | Explicit dependencies and cycle rejection. |
| FeatureKey/cache | IMPLEMENTED | Canonical semantics and bounded isolated LRU. |
| FeatureSnapshot | IMPLEMENTED | Immutable Prompt 5/optional Prompt 6 lineage. |
| Mandatory/optional health | IMPLEMENTED | Priority aggregation preserves failure type. |
| Recovery/observability/readiness | IMPLEMENTED | Minimal state and central service integration. |

## Tests

- Prompt 7 focused tests: PASS
- Prompt 1–6 regression: PASS
- Full suite: **278 passed, 0 failed, 0 skipped**
- Temporal integrity suite: PASS
- Reference vector verification: PASS
- Failure/invariant tests: PASS
- Compilation and lifecycle smoke: PASS
- Safety source scan: PASS

## Performance Test

- Bars: 6,000
- Instruments: one fictional instrument
- Timeframes: H4, H1, M15
- Features: eight-feature core bundle per timeframe
- Duration: **0.11 seconds** in the supplied Linux environment
- Cache: remained under 100 configured entries
- This is a bounded test, not a production-scale claim.

## Windows Compatibility

- Native Windows tested: NO
- Static portability: PASS
- New dependencies: none
- No hard-coded path, GUI, shell, or OS-specific dependency introduced
- **WINDOWS VERIFICATION PENDING:** native service execution, restart/rebuild,
  memory profiling, and long-run cache behavior.

## Safety Verification

No broker connectivity/authentication, live feed, real/demo execution,
leveraged execution engine, order placement, or platform bypass exists. The
feature engine contains mathematical measurements only and no buy/sell,
strategy, or regime interpretation. Invalid values remain explicit and future
observations cannot alter historical calculations.

## Requirement-by-Requirement Gap Scan

| Requirement | Classification | Note |
|---|---|---|
| 7.0–7.5 purpose, upstream, boundary, portability, ownership, pipeline | IMPLEMENTED | Market domain extended without duplication. |
| 7.6–7.11 input, health, values, identity, canonicalization | IMPLEMENTED | Structured values and complete canonical keys. |
| 7.12–7.18 sources, bar state, shift, temporal, warm-up | IMPLEMENTED | Explicit deterministic semantics. |
| 7.19–7.22 EMA | IMPLEMENTED | SMA seed and derived MA measurements. |
| 7.23–7.26 TR/ATR | IMPLEMENTED | Wilder definition and percent-price normalization. |
| 7.27–7.28 ADX | IMPLEMENTED | DM/DI/DX/ADX dependency chain. |
| 7.29–7.31 RSI | IMPLEMENTED | Edge cases safe; no interpretation. |
| 7.32–7.34 MACD | IMPLEMENTED | Main/signal/histogram/slope. |
| 7.35–7.38 Bollinger | IMPLEMENTED | Population convention and zero-width protection. |
| 7.39–7.40 candle anatomy | IMPLEMENTED | Ratios preserve zero-range error state. |
| 7.41–7.49 returns, ROC, displacement, MA features | IMPLEMENTED | Explicit names and units. |
| 7.50–7.55 volatility/percentile/expansion | IMPLEMENTED | No silent annualization; ratio below one also measures compression. |
| 7.56–7.59 range/ATR normalization | IMPLEMENTED | Numerator, denominator and units exposed. |
| 7.60–7.64 numerical safety/dependency DAG | IMPLEMENTED | Unsafe results blocked and cycles rejected. |
| 7.65–7.68 cache | IMPLEMENTED | Complete isolation and bounded eviction. |
| 7.69–7.72 incremental/rebuild | PARTIALLY IMPLEMENTED | Deterministic rebuild and equivalence pass; calculations currently reuse cache but do not persist recursive suffix-only states. Non-blocking correctness debt. |
| 7.73–7.80 snapshots/multi-timeframe/instrument | IMPLEMENTED | Consistent lineage across configured roles. |
| 7.81–7.85 bundles/lazy/availability/health | IMPLEMENTED | Caller-specified demand-driven bundles and mandatory/optional aggregation. |
| 7.86–7.91 observability/error/readiness/recovery | IMPLEMENTED | Existing frameworks reused; derived state cannot outrank source. |
| 7.92–7.94 configuration/strict mode | IMPLEMENTED | Prompt 2 extended and invalid MACD/EMA combinations rejected. |
| 7.95–7.96 performance/resources | IMPLEMENTED | Bounded cache and requested-only outputs. |
| 7.97–7.103 fixtures/tests/invariants | IMPLEMENTED | Deterministic generated fixtures and reference values. |
| 7.104 performance | IMPLEMENTED | 6,000 bars measured. |
| 7.105 Windows | PARTIALLY IMPLEMENTED | Static pass; native run pending. |
| 7.106 regression | IMPLEMENTED | Prompt 1–6 preserved. |
| 7.107 non-goals | IMPLEMENTED | No interpretation, strategy, risk, or execution. |
| 7.108 definition of done | IMPLEMENTED | Correctness contracts met; suffix-state optimization is technical debt. |
| 7.109–7.113 reports/baseline/downstream/final | IMPLEMENTED | Baseline updated; stopped before Prompt 8. |

## Safety-Scope Deferments

- All live, account, platform, and broker inputs remain prohibited.
- No actionable trading interpretation or execution output is produced.

## Technical Debt and Known Issues

- Native Windows Server verification remains pending.
- Stateful suffix-only incremental persistence is not implemented; deterministic
  full rebuild and bounded cache reuse are authoritative.
- Annualized volatility is not exposed, avoiding an implicit market-calendar
  assumption. A future explicit research calendar may supply a factor.
- Named preset bundles are caller-composed rather than stored in a separate
  registry; every request remains canonical and deterministic.

## Phase II Baseline Update

Prompt 8 onward must reuse these formula, initialization, smoothing, price
source, shift, warm-up, FeatureKey, snapshot, numerical-safety, rolling-window,
percentile, temporal-integrity, and rebuild contracts. Downstream modules must
not independently recalculate owned features.
