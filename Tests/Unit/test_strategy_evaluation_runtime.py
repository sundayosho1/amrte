from __future__ import annotations

from dataclasses import replace
from datetime import timezone

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.intelligence import IntelligenceAvailability, IntelligenceHealth
from amrte.market.intelligence_runtime import UnifiedMarketIntelligenceSnapshot, market_intelligence_schema_identity
from amrte.strategies.evaluation_runtime import (
    StrategyEvaluationRuntime,
    StrategyEvaluationRuntimeAcceptance,
    default_strategy_registry,
    research_candidate_schema_identity,
    strategy_evaluation_set_schema_identity,
)
from amrte.strategies.framework import DetectionState, SignalDirection, StrategyRegistry
from Tests.Unit.test_events import NOW
from Tests.Unit.test_strategy_framework import TestStrategy, intelligence


def unified_snapshot(intel=None, *, schema_identity=None):
    intel = intel or intelligence()
    return UnifiedMarketIntelligenceSnapshot(
        "P41-U-" + intel.market_intelligence_snapshot_id,
        "1.0",
        schema_identity or market_intelligence_schema_identity(),
        "P41-FP-" + intel.market_intelligence_snapshot_id,
        NOW,
        intel.as_of_timestamp_utc,
        intel.as_of_timestamp_utc,
        "TRO-1",
        "OBS-1",
        "OBS-FP-1",
        "TRUSTED",
        "Q-1",
        "SRC-HEALTH-1",
        intel.dataset_id,
        intel.dataset_fingerprint,
        "OFFLINE-P42",
        intel.instrument_id,
        "M15",
        intel.market_intelligence_snapshot_id,
        intel,
        {},
        intel.overall_intelligence_health,
        intel.intelligence_availability,
        intel.restrictions,
        intel.warnings,
        intel.reason_codes,
        False,
        "NONE",
        intel.configuration_snapshot_id,
        intel.recovery_epoch,
    )


def runtime_with(*strategies):
    registry = StrategyRegistry()
    for strategy in strategies:
        registry.register(strategy)
    return StrategyEvaluationRuntime(clock=FixedClock(NOW), audit=InMemoryAuditSink(), registry=registry)


def test_schema_identities_are_deterministic_and_default_registry_is_truthful():
    assert research_candidate_schema_identity() == research_candidate_schema_identity()
    assert strategy_evaluation_set_schema_identity() == strategy_evaluation_set_schema_identity()
    registry = default_strategy_registry()
    ids = tuple(strategy.metadata.identity.strategy_id for strategy in registry.all())
    assert ids == (
        "S1_TREND_PULLBACK",
        "S2_BREAKOUT_VOLATILITY_EXPANSION_IMMEDIATE",
        "S2_BREAKOUT_VOLATILITY_EXPANSION_RETEST",
        "S3_RANGE_MEAN_REVERSION",
    )


def test_p41_snapshot_is_only_authoritative_input_boundary():
    runtime = runtime_with(TestStrategy())
    blocked = runtime.evaluate_unified_snapshot(unified_snapshot(schema_identity="bad-schema"))
    assert blocked.acceptance is StrategyEvaluationRuntimeAcceptance.BLOCKED
    assert "P42_P41_SCHEMA_IDENTITY_MISMATCH" in blocked.reason_codes

    bad_intel = replace(
        intelligence(),
        intelligence_availability=IntelligenceAvailability.NOT_AVAILABLE,
        overall_intelligence_health=IntelligenceHealth.UNAVAILABLE,
        market_intelligence_snapshot_id="UNAVAILABLE",
    )
    unavailable = runtime.evaluate_unified_snapshot(unified_snapshot(bad_intel))
    assert unavailable.acceptance is StrategyEvaluationRuntimeAcceptance.BLOCKED
    assert "P42_INTELLIGENCE_UNAVAILABLE" in unavailable.reason_codes
    assert not hasattr(runtime, "evaluate_raw_observation")
    assert not hasattr(runtime, "evaluate_trusted_observation")


def test_candidate_and_no_candidate_accounting_is_immutable_and_research_only():
    candidate_strategy = TestStrategy("CANDIDATE", direction=SignalDirection.LONG_BIAS)
    no_candidate_strategy = TestStrategy("NO_CANDIDATE", detect=DetectionState.NOT_DETECTED)
    runtime = runtime_with(candidate_strategy, no_candidate_strategy)

    result = runtime.evaluate_unified_snapshot(unified_snapshot())
    evaluation_set = result.evaluation_set

    assert result.acceptance is StrategyEvaluationRuntimeAcceptance.ACCEPTED
    assert evaluation_set.strategies_considered == ("CANDIDATE", "NO_CANDIDATE")
    assert evaluation_set.strategies_eligible == ("CANDIDATE", "NO_CANDIDATE")
    assert len(evaluation_set.candidates) == 1
    candidate = evaluation_set.candidates[0]
    assert candidate.strategy_id == "CANDIDATE"
    assert candidate.market_intelligence_snapshot_id == evaluation_set.market_intelligence_snapshot_id
    assert candidate.trusted_observation_id == "TRO-1"
    assert candidate.knowledge_cutoff_utc == evaluation_set.knowledge_cutoff_utc
    assert "RESEARCH_CANDIDATE_NOT_AUTHORIZATION" in candidate.reason_codes
    assert evaluation_set.no_candidate_outcomes == ("NO_CANDIDATE",)
    assert evaluation_set.scoring_active is False
    assert evaluation_set.arbitration_active is False
    assert evaluation_set.final_decision_active is False


def test_conflicting_candidates_are_preserved_without_arbitration():
    runtime = runtime_with(
        TestStrategy("BULL", direction=SignalDirection.LONG_BIAS),
        TestStrategy("BEAR", direction=SignalDirection.SHORT_BIAS),
    )
    evaluation_set = runtime.evaluate_unified_snapshot(unified_snapshot()).evaluation_set

    assert {candidate.research_direction for candidate in evaluation_set.candidates} == {"BULLISH", "BEARISH"}
    assert len(evaluation_set.candidates) == 2
    assert evaluation_set.arbitration_active is False
    assert evaluation_set.final_decision_active is False


def test_duplicate_recovery_and_replay_equivalence():
    runtime = runtime_with(TestStrategy())
    snapshot = unified_snapshot()
    first = runtime.evaluate_unified_snapshot(snapshot).evaluation_set
    duplicate = runtime.evaluate_unified_snapshot(snapshot)
    assert duplicate.acceptance is StrategyEvaluationRuntimeAcceptance.DUPLICATE
    assert duplicate.evaluation_set.evaluation_set_id == first.evaluation_set_id

    state = runtime.recovery_state(0)
    restored = runtime_with(TestStrategy())
    assert restored.restore(state, 0)
    assert restored.reconcile(0) == ()

    next_snapshot = unified_snapshot(replace(intelligence(), market_intelligence_snapshot_id="NEXT"))
    continuous = runtime.evaluate_unified_snapshot(next_snapshot).evaluation_set
    restored_result = restored.evaluate_unified_snapshot(next_snapshot).evaluation_set
    assert restored_result.evaluation_set_id == continuous.evaluation_set_id
    assert restored_result.evaluation_fingerprint == continuous.evaluation_fingerprint


def test_instrument_dataset_and_strategy_isolation():
    runtime = runtime_with(TestStrategy("A"), TestStrategy("B"))
    alpha = runtime.evaluate_unified_snapshot(unified_snapshot()).evaluation_set
    beta_intel = replace(
        intelligence(),
        instrument_id="FICTIONAL_BETA",
        dataset_id="DS-B",
        dataset_fingerprint="FP-B",
        market_intelligence_snapshot_id="BETA",
    )
    beta = runtime.evaluate_unified_snapshot(unified_snapshot(beta_intel)).evaluation_set

    assert alpha.instrument_id == "FICTIONAL_ALPHA"
    assert beta.instrument_id == "FICTIONAL_BETA"
    assert alpha.dataset_id != beta.dataset_id
    assert len(runtime.diagnostics()["latest_evaluation_set"]["strategies_considered"]) == 2
