# AMRTE Exit Management Research

Version 0.20.0 provides an offline, deterministic exit-management model for fictional research exposure. It cannot submit, modify, or close broker positions.

## Authority and lifecycle

Prompt 6 supplies structural evidence, Prompt 9 supplies UTC/session/`TradingDayID` semantics, Prompt 19 supplies thesis invalidation and normalized invalidation distance, and Prompts 17–18 supply final fictional exposure. Prompt 20 consumes those artifacts without recomputing them.

An immutable `ResearchExitPlan` contains deterministic stages and fractions. Immutable `ResearchExitEvent` records append reductions to the bounded `ResearchExitLedger`. `ExitManagementState` is the immutable Prompt 21 handoff. A runner is only the remaining exposure after completed stages.

## Target and accounting semantics

For bullish research, a fixed target is `reference + R * invalidation_distance`; bearish research uses the symmetric subtraction. This is `NormalizedResearchR`, not broker-realized financial reward/risk.

Structural targets must be confirmed and available by plan time, match strategy/signal lineage, and lie in the favorable direction. Missing structure is not fabricated. Stage fractions and runner ownership must sum consistently and can never exceed the initial exposure.

Reductions use deterministic floor quantization. At every event:

`0 <= exposure_after <= exposure_before` and `total_reduced <= initial_exposure`.

## Observation and ambiguity semantics

`TOUCH` uses the authoritative high/low; `CLOSE_AT_OR_BEYOND` uses the authoritative close and confirms no earlier than its availability time. Multi-stage crossings process in stage order.

If one bar contains both target and invalidation evidence without authoritative ordering, the default result is `AMBIGUOUS_NO_RESULT`. Invalidation can be selected conservatively. A lower-timeframe ordering hint is accepted only as already-authoritative evidence; Prompt 20 does not fabricate ticks or fills.

## Time and state exits

Maximum bars, elapsed research time, session end, and Prompt 9 `TradingDayID` transitions are supported. Regime states are consumed as authoritative labels; Prompt 20 does not recalculate regime. Confirmed Prompt 19 invalidation has precedence over favorable targets.

## Recovery and limits

Plans, targets, events, caches, and ledger entries are bounded. Recovery validates engine version and configuration snapshot before restoring. Event identity includes plan, stage/reason, observation, and accounting values, preventing duplicate reductions during replay.

## Deliberate boundaries

Break-even, trailing, broker fills, live P&L, costs, leverage, margin, and financial realized reward/risk are absent. Prompt 21 may consume `ExitManagementState`; it must not reinterpret completed Prompt 20 accounting.
