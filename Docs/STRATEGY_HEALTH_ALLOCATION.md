# Strategy health and fictional research allocation

AMRTE v0.24.0 adds an offline strategy-health restriction layer after Prompt
23. It consumes completed, immutable normalized-R outcome observations derived
from Prompt 20 completion records. Open hypotheses, partial exits, and runners
are not independently counted as completed outcomes.

The engine calculates bounded rolling statistics including observation count,
cumulative/mean/median normalized R, win/loss/neutral rates, positive and
negative averages, expectancy, equity peak, maximum drawdown, consecutive
negative outcomes, dispersion, downside deviation, and holding duration.

Expected behavior is represented by immutable, versioned profiles with explicit
provenance and point-in-time availability. Strategy ID, version, variant,
family, regime, dataset, configuration, and recovery lineage remain explicit.

Published health states are `HEALTHY`, `CAUTION`, `DEFENSIVE`, and `SUSPENDED`.
Operational states include insufficient history, stale, invalid, and unknown.
Raw and published states are separate. Restrictive transitions may occur
quickly; recovery requires new evidence, sequential confirmation, and cooldown.
Repeated evaluation of the same outcome set cannot advance confirmation.

Allocation multipliers are bounded from zero through one. Healthy preserves
Prompt 23 exposure; it does not increase it. Caution and Defensive reduce it,
Suspended reduces it to zero, and insufficient history uses a conservative
probation multiplier. Family and strategy restrictions compose using the most
restrictive multiplier. Unused allocation is never reassigned automatically.

The immutable Phase V `PortfolioIntelligenceSnapshot` records Prompt 22 and 23
lineage, health snapshots, allocation decisions, final fictional admissions,
restrictions, dataset/configuration identity, as-of time, and recovery epoch.

This module has no broker, account, live-feed, leverage, margin, order,
position-management, or execution capability.

Current non-blocking limitations: rolling windows are observation-count based;
advanced change-point detection and optional relative-strategy comparison are
reserved for later analytics; native Windows execution has not been performed.
