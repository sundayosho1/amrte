# Correlation and concentration research

AMRTE v0.23.0 adds an offline, fictional correlation/dependency layer after the
Prompt 22 portfolio-capacity decision. It consumes point-in-time return
observations and immutable portfolio exposure records. It does not acquire live
data or communicate with brokers, accounts, orders, positions, margin, or
leverage services.

## Mathematical policy

For two aligned return series, the engine uses timestamp intersection and the
sample Pearson expression:

\[
\rho_{xy}=\frac{\sum_i(x_i-\bar{x})(y_i-\bar{y})}
{\sqrt{\sum_i(x_i-\bar{x})^2\sum_i(y_i-\bar{y})^2}}
\]

Only observations whose observation and availability timestamps are no later
than the evaluation time participate. The result is unavailable when lineage is
incompatible, the aligned sample is too small, either series has zero variance,
values are non-finite, or required evidence is stale. Missing or unknown
correlation is never treated as zero.

Direction-adjusted dependency is `raw correlation × direction(A) ×
direction(B)`, where bullish is +1 and bearish is -1. Only positive adjusted
dependency represents reinforcing statistical exposure. Negative or low
dependency never grants additional capacity.

## Portfolio integration

Prompt 22 remains the direct exposure/capacity authority. Prompt 23 evaluates a
candidate without committing or reserving it, then returns an immutable
`CorrelationRiskDecision`. Its approved exposure is always bounded by the
Prompt 22 approval. Correlation therefore may preserve, reduce, or block a
fictional research allocation; it cannot enlarge it.

The factor matrix uses Prompt 22's deterministic instrument decomposition.
Direct factor concentration and statistical correlation are retained as
separate evidence. The default composition is most-restrictive-only, preventing
blind additive penalties for overlapping evidence.

Pairwise dependencies above the configured entry threshold form a deterministic
undirected graph. Connected components become transitive clusters. Candidate
impact uses a non-mutating what-if projection and applies conservative,
step-quantized reductions where cluster capacity is exceeded.

## Interval, state, and recovery semantics

- Published observations, matrices, snapshots, clusters, impacts, and decisions
  are frozen values.
- IDs include source lineage, time, configuration, and engine context.
- Snapshot/decision collections and cache storage are bounded.
- Recovery metadata validates engine and configuration compatibility; derived
  matrices and clusters remain deterministically rebuildable.
- The Prompt 24 handoff contains only research identifiers, restrictions, and
  the final fictional exposure allowed by Prompt 23.

## Remediation additions in v0.23.1

- Dedicated immutable square correlation matrices preserve diagonal validity,
  symmetry, unknown cells, health, lineage, window identity, and deterministic IDs.
- Coordinated multi-window intelligence supports most-restrictive and weighted
  aggregation with explicit required-window policies.
- Published cluster state is separated from raw graph state. Entry/exit
  confirmation, hysteresis, cooldown, stale restriction, merge/split lineage,
  immutable versions, and recovery state are preserved.
- Independent fictional cluster exposure, research-risk, member-count, and
  portfolio-share limits are evaluated conservatively and re-quantized.
- `NO_ACTION` is distinct from a positive candidate blocked by restrictions.

Native Windows execution was not performed; static portability passed. The
engine remains an offline research simulator and cannot access or operate any
financial account or execution venue.
