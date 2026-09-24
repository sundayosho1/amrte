# AMRTE Protective Boundary Research

Version 0.21.0 adds an offline, fictional protective-boundary engine. It cannot modify broker stops, positions, orders, accounts, leverage, or margin.

## Authority

Prompt 19 remains the immutable owner of the original thesis-invalidating boundary and normalized 1R distance. Prompt 20 remains the owner of targets, partial reductions, remaining exposure, and runners. Prompt 21 only creates more restrictive boundary versions for the remaining fictional exposure.

## Monotonic model

For bullish research a new boundary must be greater than or equal to the active boundary. For bearish research it must be less than or equal to the active boundary. Volatility expansion, restart, configuration changes, and later evidence cannot widen a published boundary or restore exited exposure.

## Candidate sources

- Break-even uses the Prompt 19 reference plus a configured zero, fixed normalized, or authoritative ATR offset.
- ATR trailing consumes externally supplied Prompt 7 evidence and an independent multiplier.
- Structure trailing consumes externally supplied, confirmed Prompt 6 evidence.
- R trailing consumes Prompt 19's normalized distance and an ordered explicit R-step schedule.
- Hybrid selection deterministically compares valid candidates using configured priority or protective ordering.

## Temporal semantics

Evidence must be available at evaluation time. A boundary derived from a completed observation cannot be treated as active earlier inside that observation. The implemented default rejects a new boundary when the same observation also crosses it, preserving the prior active boundary. Close-confirmed events use the observation availability time and are never backdated.

## State and recovery

Every update creates an immutable `ProtectiveBoundaryVersion` linked to its parent and original Prompt 19 decision. The bounded `ProtectiveBoundaryLedger` stores versions, events, and the active state. Recovery validates the engine/configuration identity and refuses a state whose active value does not match its active version.

## Limitations

Authoritative lower-timeframe ordering is not internally resolved; ambiguous cases keep the prior boundary. Multi-close and structural-confirmation aggregation require upstream-confirmed evidence. Custom-registered activation/trailing methods are contracts only. Detailed noise-zone enforcement and synthesized consensus boundaries remain extensions. These limitations do not permit boundary loosening or optimistic historical ordering.
