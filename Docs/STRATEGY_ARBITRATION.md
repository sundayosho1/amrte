# Strategy Arbitration and Conflict Resolution

AMRTE v0.16.0 completes the Phase III research strategy layer with centralized arbitration. Strategies propose immutable Prompt 11/12 artifacts; `StrategyArbitrationEngine` freezes and validates them, normalizes them into `StrategyOpinion` records, builds an order-independent arbitration group, assesses every pair, applies an explicit policy, and publishes a `StrategyDecisionSnapshot`.

The default `HYBRID_CONSERVATIVE` policy preserves upstream restrictions, excludes invalid, unhealthy, incomplete, future, or expired hypotheses, prefers a single regime-native hypothesis only when metadata provides a clear distinction, requires meaningful quality/confidence separation for other preferences, and abstains when opposition remains ambiguous. A higher score is never an automatic winner.

Same-direction outputs coexist only under configured combination policy. Opposite-direction outputs never coexist by default. Duplicate and overlapping upstream evidence is recorded rather than counted as independent confirmation. The original strategy artifacts remain immutable when an opinion is preferred or suppressed.

`StrategyDecisionSnapshot` is the authoritative Phase III output for Phase IV. It is research metadata only and carries no brokerage, account, financial sizing, stop, target, position, or execution capability.

