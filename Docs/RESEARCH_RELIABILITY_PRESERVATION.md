# Research Reliability Preservation Engine

AMRTE v0.24.4 implements a neutral reliability-preservation layer over abstract quality-point outcomes. It does not model money, capital, profit/loss, accounts, markets, positions, or financial participation.

Each scope starts from a configured `ResearchReliabilityIndex`. Immutable `QualityOutcomeDelta` records may raise or lower the index. The `best_value` is monotonic. Absolute and relative deterioration are calculated against that best mark with explicit denominator safety.

Published stages are `NORMAL`, `WATCH`, `RESTRICTED`, `PROTECTED`, and `SUSPENDED`. Deterioration applies immediately; improvement requires configured confirmation and recovers at most one stage per confirmation cycle. Permission multipliers remain within `[0, 1]`, so this layer can never amplify upstream research permission.

The engine provides point-in-time snapshots, deterioration episodes and duration, deterministic event sequencing, duplicate/out-of-order prevention, scope/dataset/configuration isolation, non-mutating reconciliation, fail-closed recovery, deterministic replay fingerprints, bounded state, audit hooks, and DecisionTrace.

This is generic research-quality governance only. It has no broker, account, order, fill, position, market price, leverage, margin, or real/demo execution capability.
