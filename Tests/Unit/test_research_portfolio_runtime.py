from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.portfolio.correlation import ReturnObservation, ReturnSeries
from amrte.portfolio.research_portfolio_runtime import (
    CandidatePortfolioContext,
    PortfolioConflictType,
    PortfolioResearchAcceptance,
    PortfolioResearchStateValue,
    ResearchPortfolioRuntime,
    ResearchPortfolioRuntimeConfiguration,
    candidate_research_risk_schema_identity,
    correlation_research_schema_identity,
    portfolio_research_snapshot_schema_identity,
)
from amrte.strategies.framework import DetectionState, SignalDirection
from amrte.strategies.research_scoring_runtime import ResearchScoringRuntime
from Tests.Unit.test_events import NOW
from Tests.Unit.test_strategy_evaluation_runtime import runtime_with, unified_snapshot
from Tests.Unit.test_strategy_framework import TestStrategy


def p43_assessment_for(*strategies, snapshot=None):
    p42 = runtime_with(*(strategies or (TestStrategy("S1"),)))
    snapshot = snapshot or unified_snapshot()
    evaluation_set = p42.evaluate_unified_snapshot(snapshot).evaluation_set
    p43 = ResearchScoringRuntime(
        clock=FixedClock(NOW),
        audit=InMemoryAuditSink(),
        registry=p42.registry,
    )
    assessment = p43.assess(evaluation_set, snapshot.market_intelligence).assessment
    return p42, snapshot, evaluation_set, assessment


def contexts_for(p42, evaluation_set, assessment, **overrides):
    candidate_by_id = {item.candidate_id: item for item in evaluation_set.candidates}
    metadata_by_strategy = {
        strategy.metadata.identity.strategy_id: strategy.metadata
        for strategy in p42.registry.all()
    }
    contexts = []
    instruments = overrides.get("instruments", {})
    directions = overrides.get("directions", {})
    families = overrides.get("families", {})
    variants = overrides.get("variants", {})
    for scored in assessment.scored_candidates:
        candidate = candidate_by_id[scored.candidate_id]
        metadata = metadata_by_strategy[scored.strategy_id]
        contexts.append(
            CandidatePortfolioContext.create(
                candidate_id=scored.candidate_id,
                scored_candidate_id=scored.scored_candidate_id,
                instrument_id=instruments.get(scored.candidate_id, candidate.instrument_id),
                strategy_id=scored.strategy_id,
                strategy_version=scored.strategy_version,
                strategy_family=families.get(scored.candidate_id, metadata.identity.family.name),
                strategy_variant=variants.get(scored.candidate_id),
                research_direction=directions.get(scored.candidate_id, candidate.research_direction),
                dataset_id=candidate.dataset_id,
                dataset_fingerprint=candidate.dataset_fingerprint,
                timeframe=candidate.timeframe,
                market_intelligence_snapshot_id=candidate.market_intelligence_snapshot_id,
                knowledge_cutoff_utc=assessment.knowledge_cutoff_utc,
                configuration_identity=assessment.configuration_identity,
                recovery_epoch=assessment.recovery_epoch,
            )
        )
    return tuple(contexts)


def return_series(instrument_id, values, *, dataset_id="DS-1", dataset_fingerprint="FP-1"):
    observations = tuple(
        ReturnObservation(
            instrument_id,
            "M15",
            NOW - timedelta(minutes=(len(values) - index - 1) * 15),
            NOW - timedelta(minutes=(len(values) - index - 1) * 15),
            Decimal(str(value)),
            "CLOSE_TO_CLOSE",
            dataset_id,
            dataset_fingerprint,
            f"{instrument_id}-{index}",
        )
        for index, value in enumerate(values)
    )
    return ReturnSeries.create(
        instrument_id,
        "M15",
        observations,
        dataset_id,
        dataset_fingerprint,
        NOW,
    )


def test_schema_identities_are_deterministic_and_distinct_from_p43():
    assert candidate_research_risk_schema_identity() == candidate_research_risk_schema_identity()
    assert correlation_research_schema_identity() == correlation_research_schema_identity()
    assert portfolio_research_snapshot_schema_identity() == portfolio_research_snapshot_schema_identity()
    assert len(
        {
            candidate_research_risk_schema_identity(),
            correlation_research_schema_identity(),
            portfolio_research_snapshot_schema_identity(),
        }
    ) == 3


def test_valid_p43_assessment_creates_research_only_portfolio_snapshot():
    p42, _, evaluation_set, assessment = p43_assessment_for(TestStrategy("S1"))
    runtime = ResearchPortfolioRuntime(clock=FixedClock(NOW), audit=InMemoryAuditSink())
    result = runtime.assess(assessment, contexts_for(p42, evaluation_set, assessment))
    snapshot = result.snapshot

    assert result.acceptance is PortfolioResearchAcceptance.ACCEPTED
    assert snapshot.p43_assessment_id == assessment.assessment_id
    assert snapshot.candidate_risk_assessments[0].research_weight == Decimal("1")
    assert "RESEARCH_WEIGHT_NOT_POSITION_SIZE" in snapshot.candidate_risk_assessments[0].reason_codes
    assert "PORTFOLIO_COMPATIBLE_NOT_CAPITAL_ALLOCATION" in snapshot.reason_codes
    assert runtime.diagnostics()["financial_execution"] == "NONE"


def test_invalid_or_mutated_p43_evidence_is_blocked_before_portfolio_state():
    p42, _, evaluation_set, assessment = p43_assessment_for(TestStrategy("S1"))
    runtime = ResearchPortfolioRuntime(clock=FixedClock(NOW), audit=InMemoryAuditSink())
    blocked = runtime.assess(
        replace(assessment, schema_identity="bad-schema"),
        contexts_for(p42, evaluation_set, assessment),
    )

    assert blocked.acceptance is PortfolioResearchAcceptance.BLOCKED
    assert "P44_P43_ASSESSMENT_SCHEMA_MISMATCH" in blocked.reason_codes
    assert runtime.snapshots == {}


def test_missing_candidate_context_is_unavailable_not_default_zero():
    _, _, _, assessment = p43_assessment_for(TestStrategy("S1"))
    result = ResearchPortfolioRuntime(clock=FixedClock(NOW), audit=InMemoryAuditSink()).assess(assessment)
    snapshot = result.snapshot

    assert result.acceptance is PortfolioResearchAcceptance.ACCEPTED
    assert snapshot.portfolio_research_state == PortfolioResearchStateValue.UNAVAILABLE.value
    assert "P44_CONTEXT_UNAVAILABLE" in snapshot.candidate_risk_assessments[0].reason_codes
    assert any(item.reason_code == "P44_CONTEXT_UNAVAILABLE" for item in snapshot.aggregate_restrictions)
    assert snapshot.correlation_snapshot_id


def test_no_candidate_p43_assessment_becomes_no_action_without_failure():
    p42, _, evaluation_set, assessment = p43_assessment_for(
        TestStrategy("NO", detect=DetectionState.NOT_DETECTED)
    )
    result = ResearchPortfolioRuntime(clock=FixedClock(NOW), audit=InMemoryAuditSink()).assess(
        assessment,
        contexts_for(p42, evaluation_set, assessment),
    )

    assert result.acceptance is PortfolioResearchAcceptance.ACCEPTED
    assert result.snapshot.portfolio_research_state == PortfolioResearchStateValue.NO_ACTION.value
    assert result.snapshot.candidate_risk_assessments == ()


def test_same_instrument_same_direction_records_hypothesis_overlap():
    p42, _, evaluation_set, assessment = p43_assessment_for(
        TestStrategy("A", direction=SignalDirection.LONG_BIAS),
        TestStrategy("B", direction=SignalDirection.LONG_BIAS),
    )
    result = ResearchPortfolioRuntime(clock=FixedClock(NOW), audit=InMemoryAuditSink()).assess(
        assessment,
        contexts_for(p42, evaluation_set, assessment),
    )

    conflict_types = {item.conflict_type for item in result.snapshot.portfolio_conflicts}
    assert PortfolioConflictType.HYPOTHESIS_OVERLAP.value in conflict_types


def test_same_instrument_opposing_directions_record_directional_conflict():
    p42, _, evaluation_set, assessment = p43_assessment_for(
        TestStrategy("BULL", direction=SignalDirection.LONG_BIAS),
        TestStrategy("BEAR", direction=SignalDirection.SHORT_BIAS),
    )
    result = ResearchPortfolioRuntime(clock=FixedClock(NOW), audit=InMemoryAuditSink()).assess(
        assessment,
        contexts_for(p42, evaluation_set, assessment),
    )

    assert any(
        item.conflict_type == PortfolioConflictType.DIRECTIONAL_CONFLICT.value
        for item in result.snapshot.portfolio_conflicts
    )


def test_strategy_family_and_capacity_concentration_are_restrictions():
    p42, _, evaluation_set, assessment = p43_assessment_for(TestStrategy("A"), TestStrategy("B"))
    runtime = ResearchPortfolioRuntime(
        ResearchPortfolioRuntimeConfiguration(
            maximum_same_strategy_family_candidates=1,
            maximum_simultaneous_research_candidates=1,
        ),
        clock=FixedClock(NOW),
        audit=InMemoryAuditSink(),
    )
    result = runtime.assess(assessment, contexts_for(p42, evaluation_set, assessment))

    conflict_types = {item.conflict_type for item in result.snapshot.portfolio_conflicts}
    reasons = {item.reason_code for item in result.snapshot.aggregate_restrictions}
    assert PortfolioConflictType.STRATEGY_FAMILY_CONFLICT.value in conflict_types
    assert PortfolioConflictType.CAPACITY_CONFLICT.value in conflict_types
    assert "PORTFOLIO_CAPACITY_RESTRICTED" in reasons


def test_missing_correlation_series_is_not_treated_as_zero_correlation():
    p42, _, evaluation_set, assessment = p43_assessment_for(TestStrategy("A"), TestStrategy("B"))
    second_id = assessment.scored_candidates[1].candidate_id
    contexts = contexts_for(
        p42,
        evaluation_set,
        assessment,
        instruments={second_id: "FICTIONAL_BETA"},
    )
    runtime = ResearchPortfolioRuntime(clock=FixedClock(NOW), audit=InMemoryAuditSink())
    result = runtime.assess(
        assessment,
        contexts,
    )
    correlation = runtime.correlation_snapshots[result.snapshot.correlation_snapshot_id]
    pairwise = correlation.pairwise_evidence[0]

    assert correlation.snapshot_id
    assert any(item.reason_code == "CORRELATION_INSUFFICIENT_HISTORY" for item in result.snapshot.aggregate_restrictions)
    assert pairwise["correlation"] is None
    assert pairwise["adjusted_dependency"] is None


def test_positive_point_in_time_correlation_creates_cluster_restriction():
    p42, _, evaluation_set, assessment = p43_assessment_for(TestStrategy("A"), TestStrategy("B"))
    second_id = assessment.scored_candidates[1].candidate_id
    contexts = contexts_for(
        p42,
        evaluation_set,
        assessment,
        instruments={second_id: "FICTIONAL_BETA"},
    )
    dataset_id = contexts[0].dataset_id
    dataset_fingerprint = contexts[0].dataset_fingerprint
    series = {
        "FICTIONAL_ALPHA": return_series("FICTIONAL_ALPHA", range(1, 26), dataset_id=dataset_id, dataset_fingerprint=dataset_fingerprint),
        "FICTIONAL_BETA": return_series("FICTIONAL_BETA", range(2, 52, 2), dataset_id=dataset_id, dataset_fingerprint=dataset_fingerprint),
    }
    runtime = ResearchPortfolioRuntime(clock=FixedClock(NOW), audit=InMemoryAuditSink())
    result = runtime.assess(assessment, contexts, series)
    pairwise = runtime.correlation_snapshots[result.snapshot.correlation_snapshot_id].pairwise_evidence[0]

    assert pairwise["health"] == "HEALTHY"
    assert Decimal(pairwise["adjusted_dependency"]) >= Decimal("0.75")
    assert any(item.reason_code == "PORTFOLIO_CORRELATION_CLUSTER" for item in result.snapshot.aggregate_restrictions)


def test_recovery_restore_duplicate_and_reconcile_are_deterministic():
    p42, _, evaluation_set, assessment = p43_assessment_for(TestStrategy("S1"))
    contexts = contexts_for(p42, evaluation_set, assessment)
    runtime = ResearchPortfolioRuntime(clock=FixedClock(NOW), audit=InMemoryAuditSink())
    first = runtime.assess(assessment, contexts).snapshot
    state = runtime.recovery_state(0)

    restored = ResearchPortfolioRuntime(clock=FixedClock(NOW), audit=InMemoryAuditSink())
    assert restored.restore(state, 0)
    assert restored.reconcile(0) == ()
    duplicate = restored.assess(assessment, contexts)
    assert duplicate.acceptance is PortfolioResearchAcceptance.DUPLICATE
    assert duplicate.snapshot.portfolio_snapshot_id == first.portfolio_snapshot_id

    bad = replace(state, configuration_identity="other")
    diverged = ResearchPortfolioRuntime(clock=FixedClock(NOW), audit=InMemoryAuditSink())
    assert not diverged.restore(bad, 0)
    assert diverged.reconcile(0) == ("P44_RECOVERY_RESTRICTED",)


def test_runtime_has_no_strategy_rerun_or_financial_capability_methods():
    forbidden = {
        "evaluate_raw_observation",
        "evaluate_trusted_observation",
        "assess_evaluation_set",
        "rescore_candidate",
        "rerun_arbitration",
        "submit_order",
        "place_order",
        "open_position",
        "broker_login",
        "size_position",
        "allocate_capital",
    }
    assert forbidden.isdisjoint(set(dir(ResearchPortfolioRuntime)))
