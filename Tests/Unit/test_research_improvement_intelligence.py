from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from decimal import Decimal

import pytest

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.research.improvement_intelligence import (
    CandidateStatus,
    EvidenceStrength,
    FindingType,
    Recommendation,
    ResearchImprovementPolicy,
    ResearchImprovementRuntime,
    improvement_candidate_schema_identity,
    research_failure_cluster_schema_identity,
    research_improvement_policy_identity,
    research_improvement_snapshot_schema_identity,
)
from Tests.Unit.test_events import NOW
from Tests.Unit.test_research_outcome_performance import evidence_record, future_path, runtime as p48_runtime


def runtime(tmp_path, *, max_items=128):
    return ResearchImprovementRuntime(
        clock=FixedClock(NOW + timedelta(hours=2)),
        audit=InMemoryAuditSink(),
        storage_root=tmp_path / "p49",
        maximum_candidates=max_items,
        maximum_clusters=max_items,
        maximum_snapshots=max_items,
    )


def p48_evidence(tmp_path, values, *, mutate=None, sufficient=True):
    p48, p47 = p48_runtime(tmp_path / "p48", max_items=256)
    attributions = []
    for index, value in enumerate(values, start=1):
        record = evidence_record(p47, index)
        observations = future_path(record, (100 + value, 100 + value, 100 + value))
        window = p48.update_window(record, observations, evaluation_time=observations[-1].received_at)
        attr = p48.attribute(record, window, observations, historical_reference_value=Decimal("100"))
        attributions.append(attr)
    if mutate:
        attributions = [mutate(index, attr) for index, attr in enumerate(attributions, start=1)]
    snapshot = p48.publish_snapshot()
    if sufficient:
        snapshot = replace(snapshot, sample_sufficiency="SUFFICIENT_FOR_POLICY")
    return snapshot, tuple(attributions)


def analyze(target, snapshot, attributions):
    return target.analyze(snapshot, attributions, analysis_as_of=snapshot.as_of + timedelta(seconds=1))


def test_p49_schema_policy_identities_are_deterministic():
    assert improvement_candidate_schema_identity() == improvement_candidate_schema_identity()
    assert research_failure_cluster_schema_identity() == research_failure_cluster_schema_identity()
    assert research_improvement_snapshot_schema_identity() == research_improvement_snapshot_schema_identity()
    assert research_improvement_policy_identity() == ResearchImprovementPolicy.current().policy_identity


def test_insufficient_evidence_generates_gap_not_quality_finding(tmp_path):
    target = runtime(tmp_path)
    snapshot, attributions = p48_evidence(tmp_path, (1, -1), sufficient=False)
    result = analyze(target, snapshot, attributions)
    candidates = tuple(target.candidates.values())

    assert result.candidate_count == 1
    assert candidates[0].finding_type == FindingType.RESEARCH_EVIDENCE_GAP.value
    assert candidates[0].evidence_strength == EvidenceStrength.INSUFFICIENT.value
    assert candidates[0].candidate_status == CandidateStatus.INSUFFICIENT_EVIDENCE.value
    assert candidates[0].automatic_change is False
    assert candidates[0].validation_required is True


def test_candidate_identity_lineage_immutability_and_explainability(tmp_path):
    target = runtime(tmp_path)
    snapshot, attributions = p48_evidence(
        tmp_path,
        (-4, -3, -2, 4, 4, 4),
        mutate=lambda i, a: replace(a, strategy_id="S1" if i <= 3 else "S2", strategy_version="1"),
    )
    result = analyze(target, snapshot, attributions)
    candidate = next(item for item in target.candidates.values() if item.finding_type == FindingType.STRATEGY_DEGRADATION.value)
    duplicate = analyze(target, snapshot, attributions)

    assert duplicate.snapshot_fingerprint == result.snapshot_fingerprint
    assert candidate.candidate_id == next(item for item in target.candidates.values() if item.finding_type == FindingType.STRATEGY_DEGRADATION.value).candidate_id
    assert candidate.source_snapshot_ids == (snapshot.snapshot_id,)
    assert set(candidate.source_p47_evidence_ids)
    assert candidate.supporting_evidence_refs
    assert candidate.proposed_hypothesis["automatic_change"] is False
    assert candidate.proposed_hypothesis["validation_required"] is True
    assert candidate.confidence_classification == "DESCRIPTIVE_NOT_PROBABILITY"
    with pytest.raises(FrozenInstanceError):
        candidate.automatic_change = True


def test_strategy_version_isolation_and_reference_degradation(tmp_path):
    target = runtime(tmp_path)
    snapshot, attributions = p48_evidence(
        tmp_path,
        (-5, -5, -5, 5, 5, 5),
        mutate=lambda i, a: replace(a, strategy_id="S1", strategy_version="1" if i <= 3 else "2"),
    )
    analyze(target, snapshot, attributions)
    candidate = next(item for item in target.candidates.values() if item.finding_type == FindingType.STRATEGY_DEGRADATION.value)
    assert candidate.affected_population["strategy_version"] == "1"
    assert candidate.comparison_population["reference"] == "all_strategy_population"
    assert candidate.effect_magnitude < 0


def test_regime_session_configuration_and_score_sensitivity(tmp_path):
    target = runtime(tmp_path)

    def mutate(i, a):
        weak = i <= 3
        return replace(
            a,
            regime_at_decision="RANGE" if weak else "TREND",
            session_at_decision="ASIA" if weak else "US",
            configuration_identity="CFG-A" if weak else "CFG-B",
            score_band="HIGH" if weak else "LOW",
        )

    snapshot, attributions = p48_evidence(tmp_path, (-5, -4, -4, 5, 4, 4), mutate=mutate)
    analyze(target, snapshot, attributions)
    findings = {item.finding_type for item in target.candidates.values()}
    assert FindingType.REGIME_SENSITIVITY.value in findings
    assert FindingType.SESSION_SENSITIVITY.value in findings
    assert FindingType.CONFIGURATION_SENSITIVITY.value in findings
    assert FindingType.SCORE_CALIBRATION_CONCERN.value in findings


def test_no_action_restriction_data_quality_portfolio_and_instability_patterns(tmp_path):
    target = runtime(tmp_path)

    def mutate(i, a):
        attrs = {}
        if i <= 3:
            attrs |= {"decision_classification": "NO_ACTION", "no_action_reason": "NO_ACTION_CONFLICT"}
        if 4 <= i <= 6:
            attrs |= {"decision_classification": "RESTRICTED", "restriction_state": "RESTRICTED", "protection_state": "BLOCKED"}
        if 7 <= i <= 9:
            attrs |= {"trust_state": "REJECTED", "portfolio_state": "CONCENTRATION"}
        return replace(a, **attrs)

    snapshot, attributions = p48_evidence(tmp_path, (-8, -7, 8, -6, 6, -6, 6, -6, 6), mutate=mutate)
    analyze(target, snapshot, attributions)
    findings = {item.finding_type for item in target.candidates.values()}
    assert FindingType.NO_ACTION_PATTERN.value in findings
    assert FindingType.RESTRICTION_PATTERN.value in findings
    assert FindingType.DATA_QUALITY_FAILURE_PATTERN.value in findings
    assert FindingType.PORTFOLIO_RESTRICTION_PATTERN.value in findings
    assert FindingType.OUTCOME_INSTABILITY.value in findings
    instability = next(item for item in target.candidates.values() if item.finding_type == FindingType.OUTCOME_INSTABILITY.value)
    assert instability.contradicting_evidence_refs
    assert "P49_CONTRADICTORY_EVIDENCE_PRESENT" in instability.warnings
    assert "missed" not in " ".join(item.finding_summary.lower() for item in target.candidates.values())


def test_duplicate_evidence_does_not_inflate_strength_and_clusters_are_deterministic(tmp_path):
    target = runtime(tmp_path)
    snapshot, attributions = p48_evidence(tmp_path, (-5, -5, -5, 5, 5, 5), mutate=lambda i, a: replace(a, strategy_id="S1" if i <= 3 else "S2"))
    duplicated = attributions + attributions
    analyze(target, snapshot, duplicated)
    degradation = next(item for item in target.candidates.values() if item.finding_type == FindingType.STRATEGY_DEGRADATION.value)

    assert degradation.evidence_count == 3
    assert degradation.evidence_strength in {EvidenceStrength.WEAK.value, EvidenceStrength.MODERATE.value}
    assert target.clusters
    assert tuple(target.clusters) == tuple(target.clusters)


def test_temporal_cutoff_and_schema_validation_fail_closed(tmp_path):
    target = runtime(tmp_path)
    snapshot, attributions = p48_evidence(tmp_path, (1, 2, 3))
    with pytest.raises(ValueError, match="P49_FUTURE_P48_SNAPSHOT"):
        target.analyze(snapshot, attributions, analysis_as_of=snapshot.as_of - timedelta(seconds=1))
    with pytest.raises(ValueError, match="P49_P48_SNAPSHOT_SCHEMA_MISMATCH"):
        target.analyze(replace(snapshot, schema_identity="bad"), attributions, analysis_as_of=snapshot.as_of + timedelta(seconds=1))


def test_supersession_recovery_restart_and_rebuild_equivalence(tmp_path):
    target = runtime(tmp_path)
    snapshot, attributions = p48_evidence(tmp_path, (-5, -5, -5, 5, 5, 5), mutate=lambda i, a: replace(a, strategy_id="S1" if i <= 3 else "S2"))
    analyze(target, snapshot, attributions)
    candidate = next(item for item in target.candidates.values() if item.finding_type == FindingType.STRATEGY_DEGRADATION.value)
    superseding = target.supersede_candidate(candidate.candidate_id, reason="P49_REVISION_TEST")
    state = target.recovery_state(9)
    fingerprint = target.replay_fingerprint()

    restored = runtime(tmp_path / "restore")
    assert restored.restore(state, 9)
    assert restored.replay_fingerprint() == fingerprint
    assert restored.incremental_equals_full_rebuild()
    assert superseding.supersedes_candidate_id == candidate.candidate_id
    assert not restored.restore(replace(state, policy_identity="OTHER"), 9)
    assert restored.recovery_restricted


def test_runtime_diagnostics_and_forbidden_permission_surface(tmp_path):
    target = runtime(tmp_path)
    snapshot, attributions = p48_evidence(tmp_path, (-1, 1, -1, 1))
    analyze(target, snapshot, attributions)
    diagnostics = target.diagnostics()
    forbidden = {"apply_recommendation", "change_strategy", "tune_parameters", "promote_strategy", "retire_strategy", "mutate_configuration", "authorize_execution"}
    assert diagnostics["financial_execution"] == "NONE"
    assert diagnostics["analysis_availability"] in {"AVAILABLE", "NO_IMPROVEMENT_CANDIDATE"}
    assert forbidden.isdisjoint(set(dir(target)))
