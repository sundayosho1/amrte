# Universal Research Strategy Framework

Prompt 11 introduces the common architecture every Phase III strategy must
use. Its only market input is the immutable Prompt 10
`MarketIntelligenceSnapshot`. Strategies cannot recalculate market data,
structure, features, regime, time/session, or scheduled-event risk.

## Pipeline and vocabulary

The framework distinguishes raw detection, qualification, placeholder scoring,
signal candidates, and research signals. These terms are not interchangeable.
A research signal is analytical metadata—not an order, position, risk approval,
portfolio approval, or execution approval.

Every strategy declares immutable identity, family, version, capabilities,
required timeframes/features/structure, allowed regimes, session/news
dependencies, and typed requirements. Missing mandatory capabilities fail
closed before strategy-specific detection begins.

Evidence is immutable and includes category, authoritative source module,
source snapshot, availability, health, direction, strength, and explanation.
Unavailable evidence remains unavailable; it is never converted to zero,
false, neutral, favorable, or unfavorable.

## Applicability, detection, and qualification

The orchestrator first preserves the aggregate Phase II health and availability
gate. Upstream restrictions can only stay equal or become more restrictive.
Applicable strategies then perform their own detection and qualification
through universal contracts. Qualification exposes passed, failed,
conditional, missing, and blocking rules. A hard-rule failure cannot be offset
by scoring.

`DeterministicPlaceholderScorer` exists only to verify the Prompt 11 contract.
Its normalized 0–100 score is explicitly not a probability of profit. Prompt 12
owns production confidence and quality semantics.

## Gates and safety

Risk, portfolio, protection, and execution use the universal gate contract.
At v0.11.0 the risk, portfolio, and execution gates are unavailable. Unavailable
never means approved. The framework may retain a qualified research signal for
analysis, but cannot produce an executable action. Rejected or blocked gates
remain monotonic regardless of score.

## Lifecycle, identity, and recovery

Evaluation, candidate, logical signal, signal version, and research signal IDs
are deterministic. Reprocessing an unchanged context returns the same cached
evaluation. Expiration and invalidation create new immutable versions; old
results are never mutated or backdated. Strategy state is isolated by strategy
and instrument and stores only bounded strategy-derived references.

Recovery validates the framework version and deterministic replay prevents
duplicate logical signals. Caches, histories, and recent signal references are
bounded by configuration.

## Breakout prerequisite

Prompt 7 currently lacks the bounded historical feature-series evidence needed
to prove pre-breakout compression. Prompt 11 does not duplicate or repair that
logic. The smallest compatible Prompt 7/8 extension is required before Prompt
14 implements strict breakout/expansion strategy rules.
