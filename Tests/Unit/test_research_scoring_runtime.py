from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.intelligence import IntelligenceAvailability, IntelligenceHealth
from amrte.strategies.framework import DetectionState, SignalDirection, StrategyFamily, StrategyRegistry
from amrte.strategies.research_scoring_runtime import (
    CandidateComparability,
    ResearchScoringAcceptance,
    ResearchScoringRuntime,
    ResearchScoringRuntimeConfiguration,
    ResearchArbitrationState,
    research_arbitration_assessment_schema_identity,
    scored_research_candidate_schema_identity,
)
from amrte.strategies.scoring import ScoringConfiguration
from Tests.Unit.test_events import NOW
from Tests.Unit.test_strategy_evaluation_runtime import runtime_with, unified_snapshot
from Tests.Unit.test_strategy_framework import TestStrategy, metadata


class FamilyStrategy(TestStrategy):
    def __init__(self, strategy_id: str, family: StrategyFamily, *, direction=SignalDirection.LONG_BIAS, detect=DetectionState.DETECTED):
        super().__init__(strategy_id, direction=direction, detect=detect)
        self._metadata = metadata(strategy_id, family=family)


def p42_output(*strategies, snapshot=None):
    p42 = runtime_with(*(strategies or (TestStrategy("S1"),)))
    snapshot = snapshot or unified_snapshot()
    result = p42.evaluate_unified_snapshot(snapshot)
    return p42, snapshot, result.evaluation_set


def p43_for(p42, **kwargs):
    return ResearchScoringRuntime(clock=FixedClock(NOW), audit=InMemoryAuditSink(), registry=p42.registry, **kwargs)


def test_schema_identities_are_deterministic_and_distinct_from_p42():
    assert scored_research_candidate_schema_identity() == scored_research_candidate_schema_identity()
    assert research_arbitration_assessment_schema_identity() == research_arbitration_assessment_schema_identity()
    assert scored_research_candidate_schema_identity() != research_arbitration_assessment_schema_identity()


def test_single_p42_candidate_is_scored_and_research_selected_without_authorization():
    p42, snapshot, evaluation_set = p42_output(TestStrategy("S1", direction=SignalDirection.LONG_BIAS))
    runtime = p43_for(p42)

    result = runtime.assess(evaluation_set, snapshot.market_intelligence)
    assessment = result.assessment
    scored = assessment.scored_candidates[0]

    assert result.acceptance is ResearchScoringAcceptance.ACCEPTED
    assert assessment.arbitration_state == ResearchArbitrationState.SINGLE_RESEARCH_CANDIDATE.value
    assert assessment.selected_research_candidate_id == evaluation_set.candidates[0].candidate_id
    assert scored.candidate_id == evaluation_set.candidates[0].candidate_id
    assert scored.source_signal_candidate_id == evaluation_set.candidates[0].source_signal_candidate_id
    assert scored.scoring_model_id and scored.scoring_model_version
    assert scored.normalized_score == scored.raw_score
    assert scored.threshold_state == "PASS"
    assert "HIGH_SCORE_IS_NOT_AUTHORIZATION" in assessment.reason_codes
    assert "RANK1_IS_NOT_AUTHORIZATION" in assessment.reason_codes
    assert assessment.selected_research_candidate_id is not None
    assert assessment.restrictions == ("SCORE_HEALTH_DEGRADED",)
    assert runtime.diagnostics()["financial_authorization"] == "NONE"


def test_scored_candidate_is_immutable_and_has_complete_score_provenance():
    p42, snapshot, evaluation_set = p42_output(TestStrategy("S1"))
    scored = p43_for(p42).assess(evaluation_set, snapshot.market_intelligence).assessment.scored_candidates[0]

    assert scored.candidate_fingerprint
    assert scored.score_fingerprint
    assert scored.source_score_id
    assert scored.component_scores
    assert scored.factor_scores
    assert scored.configuration_identity == "P43_RESEARCH_SCORING_DEFAULT"
    assert scored.knowledge_cutoff_utc == evaluation_set.knowledge_cutoff_utc
    with pytest.raises(FrozenInstanceError):
        scored.raw_score = 100


def test_invalid_p42_schema_and_lineage_fail_closed():
    p42, snapshot, evaluation_set = p42_output(TestStrategy("S1"))
    bad_schema = replace(evaluation_set, evaluation_schema_identity="bad-schema")
    assert p43_for(p42).assess(bad_schema, snapshot.market_intelligence).acceptance is ResearchScoringAcceptance.BLOCKED

    other_intelligence = replace(snapshot.market_intelligence, market_intelligence_snapshot_id="OTHER")
    blocked = p43_for(p42).assess(evaluation_set, other_intelligence)
    assert blocked.acceptance is ResearchScoringAcceptance.BLOCKED
    assert "P43_MARKET_INTELLIGENCE_LINEAGE_MISMATCH" in blocked.reason_codes


def test_invalid_candidate_identity_status_and_unknown_strategy_rejected():
    p42, snapshot, evaluation_set = p42_output(TestStrategy("S1"))
    candidate = evaluation_set.candidates[0]
    invalid = replace(candidate, candidate_id="bad-id")
    bad_set = replace(evaluation_set, candidates=(invalid,))
    assert "P43_CANDIDATE_IDENTITY_MISMATCH" in p43_for(p42).assess(bad_set, snapshot.market_intelligence).reason_codes

    unknown = replace(candidate, strategy_id="UNKNOWN")
    unknown_set = replace(evaluation_set, candidates=(unknown,))
    assert "P43_STRATEGY_METADATA_UNAVAILABLE" in p43_for(p42).assess(unknown_set, snapshot.market_intelligence).reason_codes


def test_no_candidate_evidence_is_accounted_without_failure():
    p42, snapshot, evaluation_set = p42_output(TestStrategy("NO", detect=DetectionState.NOT_DETECTED))
    result = p43_for(p42).assess(evaluation_set, snapshot.market_intelligence)
    assessment = result.assessment

    assert assessment.scored_candidates == ()
    assert assessment.arbitration_state == ResearchArbitrationState.NO_ELIGIBLE_CANDIDATE.value
    assert assessment.reason_codes
    assert "NO" in assessment.reason_codes


def test_threshold_boundaries_are_deterministic():
    p42, snapshot, evaluation_set = p42_output(TestStrategy("S1"))
    exact = ResearchScoringRuntimeConfiguration(scoring=ScoringConfiguration(minimum_completeness=55.555555))
    above = ResearchScoringRuntimeConfiguration(scoring=ScoringConfiguration(minimum_completeness=55.555556))
    below = ResearchScoringRuntimeConfiguration(scoring=ScoringConfiguration(minimum_completeness=55.0))

    assert p43_for(p42, configuration=exact).assess(evaluation_set, snapshot.market_intelligence).assessment.scored_candidates[0].threshold_state == "PASS"
    assert p43_for(p42, configuration=below).assess(evaluation_set, snapshot.market_intelligence).assessment.scored_candidates[0].threshold_state == "PASS"
    assert p43_for(p42, configuration=above).assess(evaluation_set, snapshot.market_intelligence).assessment.scored_candidates[0].threshold_state == "BELOW_THRESHOLD"
    with pytest.raises(ValueError, match="INVALID_MINIMUM_COMPLETENESS"):
        ResearchScoringRuntime(configuration=ResearchScoringRuntimeConfiguration(scoring=ScoringConfiguration(minimum_completeness=101)), clock=FixedClock(NOW), audit=InMemoryAuditSink())


def test_comparable_same_direction_candidates_preserve_tie_no_selection():
    p42, snapshot, evaluation_set = p42_output(
        TestStrategy("A", direction=SignalDirection.LONG_BIAS),
        TestStrategy("B", direction=SignalDirection.LONG_BIAS),
    )
    assessment = p43_for(p42).assess(evaluation_set, snapshot.market_intelligence).assessment

    assert len(assessment.scored_candidates) == 2
    assert assessment.candidate_comparisons[0].comparability is CandidateComparability.COMPARABLE
    assert assessment.ties
    assert assessment.arbitration_state == ResearchArbitrationState.TIE.value
    assert assessment.selected_research_candidate_id is None


def test_opposing_candidates_create_directional_conflict_without_forced_winner():
    p42, snapshot, evaluation_set = p42_output(
        TestStrategy("BULL", direction=SignalDirection.LONG_BIAS),
        TestStrategy("BEAR", direction=SignalDirection.SHORT_BIAS),
    )
    assessment = p43_for(p42).assess(evaluation_set, snapshot.market_intelligence).assessment

    assert assessment.conflicts
    assert any("DIRECTIONAL_CONFLICT" in conflict.conflict_types for conflict in assessment.conflicts)
    assert assessment.selected_research_candidate_id is None
    assert assessment.arbitration_state in {ResearchArbitrationState.CONFLICT.value, ResearchArbitrationState.TIE.value}


def test_breakout_mean_reversion_thesis_conflict_uses_existing_engine_categories():
    p42, snapshot, evaluation_set = p42_output(
        FamilyStrategy("S2", StrategyFamily.BREAKOUT, direction=SignalDirection.LONG_BIAS),
        FamilyStrategy("S3", StrategyFamily.MEAN_REVERSION, direction=SignalDirection.LONG_BIAS),
    )
    assessment = p43_for(p42).assess(evaluation_set, snapshot.market_intelligence).assessment

    assert any("THESIS_CONFLICT" in conflict.conflict_types for conflict in assessment.conflicts)
    assert all(conflict.resolution_state == "UNRESOLVED" for conflict in assessment.conflicts)


def test_different_scoring_models_are_explicitly_incomparable():
    p42, snapshot, evaluation_set = p42_output(
        FamilyStrategy("TREND", StrategyFamily.TREND),
        FamilyStrategy("BREAKOUT", StrategyFamily.BREAKOUT),
    )
    assessment = p43_for(p42).assess(evaluation_set, snapshot.market_intelligence).assessment

    assert any(item.comparability is CandidateComparability.INCOMPARABLE for item in assessment.candidate_comparisons)
    assert assessment.arbitration_state == ResearchArbitrationState.INCOMPARABLE.value


def test_restricted_upstream_intelligence_remains_restricted_downstream():
    p42, snapshot, evaluation_set = p42_output(TestStrategy("S1"))
    restricted_intelligence = replace(
        snapshot.market_intelligence,
        intelligence_availability=IntelligenceAvailability.AVAILABLE_WITH_RESTRICTIONS,
        overall_intelligence_health=IntelligenceHealth.DEGRADED,
        restrictions=("DEGRADED_COMPONENT",),
        market_intelligence_snapshot_id=evaluation_set.market_intelligence_snapshot_id,
    )

    assessment = p43_for(p42).assess(evaluation_set, restricted_intelligence).assessment

    assert "DEGRADED_COMPONENT" in assessment.restrictions
    assert all("DEGRADED_COMPONENT" in item.restrictions for item in assessment.scored_candidates)


def test_future_or_mutated_candidate_evidence_is_blocked_by_cutoff_and_identity():
    p42, snapshot, evaluation_set = p42_output(TestStrategy("S1"))
    candidate = evaluation_set.candidates[0]
    future = replace(candidate, knowledge_cutoff_utc=NOW.replace(year=2030))
    bad_set = replace(evaluation_set, candidates=(future,))

    result = p43_for(p42).assess(bad_set, snapshot.market_intelligence)

    assert result.acceptance is ResearchScoringAcceptance.BLOCKED
    assert "P43_KNOWLEDGE_CUTOFF_MISMATCH" in result.reason_codes


def test_repeated_scoring_and_duplicate_processing_are_idempotent():
    p42, snapshot, evaluation_set = p42_output(TestStrategy("S1"))
    runtime = p43_for(p42)

    first = runtime.assess(evaluation_set, snapshot.market_intelligence)
    duplicate = runtime.assess(evaluation_set, snapshot.market_intelligence)
    replay = p43_for(p42).assess(evaluation_set, snapshot.market_intelligence)

    assert duplicate.acceptance is ResearchScoringAcceptance.DUPLICATE
    assert duplicate.assessment.assessment_id == first.assessment.assessment_id
    assert replay.assessment.assessment_id == first.assessment.assessment_id
    assert replay.assessment.assessment_fingerprint == first.assessment.assessment_fingerprint


def test_recovery_restore_reconcile_and_restart_equivalence():
    p42, snapshot, evaluation_set = p42_output(TestStrategy("S1"))
    runtime = p43_for(p42)
    first = runtime.assess(evaluation_set, snapshot.market_intelligence).assessment
    state = runtime.recovery_state(0)

    restored = p43_for(p42)
    assert restored.restore(state, 0)
    assert restored.reconcile(0) == ()
    duplicate = restored.assess(evaluation_set, snapshot.market_intelligence)
    assert duplicate.acceptance is ResearchScoringAcceptance.DUPLICATE
    assert duplicate.assessment.assessment_id == first.assessment_id

    bad = replace(state, scoring_configuration_identity="bad")
    diverged = p43_for(p42)
    assert not diverged.restore(bad, 0)
    assert diverged.reconcile(0) == ("P43_RECOVERY_RESTRICTED",)


def test_dataset_instrument_strategy_and_configuration_isolation():
    p42, snapshot, alpha = p42_output(TestStrategy("A"))
    beta_snapshot = unified_snapshot(replace(snapshot.market_intelligence, instrument_id="FICTIONAL_BETA", dataset_id="DS-B", dataset_fingerprint="FP-B", market_intelligence_snapshot_id="BETA"))
    beta = p42.evaluate_unified_snapshot(beta_snapshot).evaluation_set

    alpha_assessment = p43_for(p42).assess(alpha, snapshot.market_intelligence).assessment
    beta_assessment = p43_for(p42).assess(beta, beta_snapshot.market_intelligence).assessment
    config_assessment = p43_for(p42, configuration=ResearchScoringRuntimeConfiguration(configuration_snapshot_id="P43_ALT")).assess(alpha, snapshot.market_intelligence).assessment

    assert alpha_assessment.assessment_id != beta_assessment.assessment_id
    assert alpha_assessment.assessment_id != config_assessment.assessment_id
    assert alpha_assessment.scored_candidates[0].strategy_id == "A"


def test_audit_metrics_and_temporal_sources_exclude_future_outcomes():
    p42, snapshot, evaluation_set = p42_output(TestStrategy("S1"))
    audit = InMemoryAuditSink()
    runtime = ResearchScoringRuntime(clock=FixedClock(NOW), audit=audit, registry=p42.registry)
    assessment = runtime.assess(evaluation_set, snapshot.market_intelligence).assessment

    assert {name for name, _ in audit.events} >= {
        "candidate_scoring_completed",
        "candidate_comparison_completed",
        "strategy_arbitration_completed",
        "post_scoring_assessment_published",
    }
    assert runtime.diagnostics()["metrics"]["candidates_scored"] == 1
    assert all("outcome" not in str(factor["source_module"]).lower() for scored in assessment.scored_candidates for factor in scored.factor_scores)


def test_no_strategy_re_evaluation_or_financial_capability_methods_exist():
    forbidden = {"evaluate_raw_observation", "evaluate_trusted_observation", "submit_order", "place_order", "open_position", "broker_login", "size_position"}
    assert forbidden.isdisjoint(set(dir(ResearchScoringRuntime)))
