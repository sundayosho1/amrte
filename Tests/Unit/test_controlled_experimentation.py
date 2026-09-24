from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from decimal import Decimal

import pytest

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.research.controlled_experimentation import (
    ConfigurationStatus,
    ControlledResearchExperimentRuntime,
    PromotionDecisionValue,
    StageStatus,
    ValidationStageName,
    research_configuration_promotion_decision_schema_identity,
    research_configuration_promotion_policy_identity,
    research_configuration_variant_schema_identity,
    research_dataset_partition_plan_schema_identity,
    research_experiment_policy_identity,
    research_experiment_result_schema_identity,
    research_experiment_specification_schema_identity,
    research_validation_metric_policy_identity,
    research_validation_stage_result_schema_identity,
    versioned_research_configuration_schema_identity,
)
from amrte.research.improvement_intelligence import FindingType
from Tests.Unit.test_events import NOW
from Tests.Unit.test_research_improvement_intelligence import analyze, p48_evidence, runtime as p49_runtime


def runtime(tmp_path, *, max_items=128):
    return ControlledResearchExperimentRuntime(
        clock=FixedClock(NOW + timedelta(hours=3)),
        audit=InMemoryAuditSink(),
        storage_root=tmp_path / "p50",
        maximum_experiments=max_items,
        maximum_configurations=max_items,
    )


def candidate(tmp_path):
    p49 = p49_runtime(tmp_path / "p49")
    snapshot, attributions = p48_evidence(
        tmp_path,
        (-5, -5, -5, 5, 5, 5),
        mutate=lambda i, a: replace(a, strategy_id="S1" if i <= 3 else "S2"),
    )
    analyze(p49, snapshot, attributions)
    item = next(value for value in p49.candidates.values() if value.finding_type == FindingType.STRATEGY_DEGRADATION.value)
    return item, snapshot


def variant(target, item):
    return target.create_configuration_variant(
        item,
        baseline_configuration_id="CONFIG-A@v3",
        challenger_configuration_id="CONFIG-A-CHALLENGER-001",
        scope="threshold",
        configuration_delta={"strategies.s1_trend_pullback.minimum_adx": 21.0},
        baseline_configuration={"strategies.s1_trend_pullback.minimum_adx": 20.0, "protection.enabled": True},
        search_space={"strategies.s1_trend_pullback.minimum_adx": (20.5, 21.0, 21.5)},
    )


def partition(target):
    return target.create_partition_plan(
        dataset_id="P50-DATASET",
        dataset_fingerprint="P50-DATASET-FP",
        source_identity="P50-SOURCE",
        instrument="AMRTE.TEST",
        timeframe="M15",
        coverage_start=NOW,
        coverage_end=NOW + timedelta(days=10),
    )


def specification(target, item, snapshot, var, plan):
    return target.register_experiment(
        item,
        source_improvement_snapshot_id=snapshot.snapshot_id,
        variant=var,
        partition_plan=plan,
        software_release_identity="P50-TEST-SOFTWARE",
    )


def passing_evidence():
    return {
        ValidationStageName.HISTORICAL.value: (Decimal("0.30"), Decimal("0.25"), Decimal("0.20")),
        ValidationStageName.OUT_OF_SAMPLE.value: (Decimal("0.20"), Decimal("0.18"), Decimal("0.16")),
        ValidationStageName.WALK_FORWARD.value: (Decimal("0.10"), Decimal("0.12")),
        ValidationStageName.ROBUSTNESS.value: (Decimal("0.15"), Decimal("0.16"), Decimal("0.14")),
        ValidationStageName.SENSITIVITY.value: (Decimal("0.10"), Decimal("0.12"), Decimal("0.11")),
    }


def test_p50_schema_and_policy_identities_are_deterministic():
    assert research_experiment_policy_identity() == research_experiment_policy_identity()
    assert research_validation_metric_policy_identity() == research_validation_metric_policy_identity()
    assert research_configuration_promotion_policy_identity() == research_configuration_promotion_policy_identity()
    assert research_experiment_specification_schema_identity() == research_experiment_specification_schema_identity()
    assert research_configuration_variant_schema_identity() == research_configuration_variant_schema_identity()
    assert research_dataset_partition_plan_schema_identity() == research_dataset_partition_plan_schema_identity()
    assert research_validation_stage_result_schema_identity() == research_validation_stage_result_schema_identity()
    assert research_experiment_result_schema_identity() == research_experiment_result_schema_identity()
    assert research_configuration_promotion_decision_schema_identity() == research_configuration_promotion_decision_schema_identity()
    assert versioned_research_configuration_schema_identity() == versioned_research_configuration_schema_identity()


def test_only_valid_p49_candidates_can_authorize_experiments(tmp_path):
    target = runtime(tmp_path)
    item, snapshot = candidate(tmp_path)
    var = variant(target, item)
    plan = partition(target)
    spec = specification(target, item, snapshot, var, plan)

    assert spec.source_improvement_candidate_id == item.candidate_id
    assert spec.financial_execution == "NONE"
    assert target.validate_improvement_candidate(item) == ()

    invalid = replace(item, automatic_change=True)
    with pytest.raises(ValueError, match="P50_P49_AUTOMATIC_CHANGE_FORBIDDEN"):
        target.register_experiment(invalid, source_improvement_snapshot_id=snapshot.snapshot_id, variant=var, partition_plan=plan, software_release_identity="P50")
    with pytest.raises(ValueError, match="P50_ORPHAN_EXPERIMENT_FORBIDDEN"):
        target.register_experiment(item, source_improvement_snapshot_id="OTHER", variant=var, partition_plan=plan, software_release_identity="P50")


def test_configuration_variant_is_immutable_bounded_and_schema_validated(tmp_path):
    target = runtime(tmp_path)
    item, _ = candidate(tmp_path)
    var = variant(target, item)

    assert var.source_improvement_candidate_id == item.candidate_id
    assert var.configuration_delta["strategies.s1_trend_pullback.minimum_adx"] == 21.0
    assert var.resolved_configuration_fingerprint
    with pytest.raises(FrozenInstanceError):
        var.scope = "strategy"
    with pytest.raises(ValueError, match="P50_CONFIGURATION_SCHEMA_UNKNOWN_FIELD"):
        target.create_configuration_variant(item, baseline_configuration_id="A", challenger_configuration_id="B", scope="threshold", configuration_delta={"unknown": 1}, baseline_configuration={})
    with pytest.raises(ValueError, match="P50_HARD_SAFETY_WEAKENING_FORBIDDEN"):
        target.create_configuration_variant(item, baseline_configuration_id="A", challenger_configuration_id="B", scope="protection research policy", configuration_delta={"protection.enabled": False}, baseline_configuration={"protection.enabled": True})


def test_partition_plan_chronology_and_holdout_exposure_tracking(tmp_path):
    target = runtime(tmp_path)
    plan = partition(target)

    assert plan.development_start < plan.development_end <= plan.validation_start < plan.validation_end
    assert plan.validation_end <= plan.out_of_sample_start < plan.out_of_sample_end <= plan.holdout_start
    assert len(plan.walk_forward_folds) == 2
    first = target.record_holdout_exposure(plan.partition_plan_id, "EXP-A")
    second = target.record_holdout_exposure(plan.partition_plan_id, "EXP-B")
    assert first.pristine is True
    assert second.pristine is False
    assert second.exposure_count == 2


def test_controlled_validation_requires_explicit_promotion_for_research_config(tmp_path):
    target = runtime(tmp_path)
    item, snapshot = candidate(tmp_path)
    var = variant(target, item)
    plan = partition(target)
    spec = specification(target, item, snapshot, var, plan)
    duplicate = specification(target, item, snapshot, var, plan)

    assert duplicate.experiment_id == spec.experiment_id
    result = target.run_validation(spec.experiment_id, passing_evidence())
    assert result.acceptance_state == "ACCEPTED"
    assert target.configurations == {}

    comparison = target.compare_champion_challenger(result.result_id)
    promotion = target.assess_promotion(result.result_id, comparison.comparison_id)
    config = next(iter(target.configurations.values()))

    assert comparison.comparable is True
    assert promotion.decision == PromotionDecisionValue.APPROVE_RESEARCH_CONFIGURATION.value
    assert config.status == ConfigurationStatus.APPROVED_RESEARCH.value
    assert config.financial_execution == "NONE"
    assert "ResearchPromotion != FinancialAuthorization" in promotion.warnings


def test_oos_failure_inconclusive_and_safety_regression_gates(tmp_path):
    target = runtime(tmp_path)
    item, snapshot = candidate(tmp_path)
    spec = specification(target, item, snapshot, variant(target, item), partition(target))

    failed = passing_evidence()
    failed[ValidationStageName.OUT_OF_SAMPLE.value] = (Decimal("-0.10"), Decimal("-0.20"), Decimal("-0.30"))
    result = target.run_validation(spec.experiment_id, failed)
    promotion = target.assess_promotion(result.result_id)
    assert promotion.decision == PromotionDecisionValue.REJECT.value
    assert "OOS_EVIDENCE_SUFFICIENT" in promotion.rejection_reasons

    target2 = runtime(tmp_path / "more")
    item2, snapshot2 = candidate(tmp_path / "more")
    spec2 = specification(target2, item2, snapshot2, variant(target2, item2), partition(target2))
    inconclusive = passing_evidence()
    inconclusive[ValidationStageName.OUT_OF_SAMPLE.value] = (Decimal("0.10"),)
    result2 = target2.run_validation(spec2.experiment_id, inconclusive)
    promotion2 = target2.assess_promotion(result2.result_id)
    assert promotion2.decision == PromotionDecisionValue.REQUIRE_MORE_EVIDENCE.value

    target3 = runtime(tmp_path / "safety")
    item3, snapshot3 = candidate(tmp_path / "safety")
    spec3 = specification(target3, item3, snapshot3, variant(target3, item3), partition(target3))
    result3 = target3.run_validation(spec3.experiment_id, passing_evidence(), safety_evidence={"protection_preservation": Decimal("-0.01")})
    promotion3 = target3.assess_promotion(result3.result_id)
    assert promotion3.decision == PromotionDecisionValue.REJECT.value
    assert "CRITICAL_REGRESSIONS_ABSENT" in promotion3.rejection_reasons


def test_walk_forward_robustness_and_sensitivity_failures_are_preserved(tmp_path):
    target = runtime(tmp_path)
    item, snapshot = candidate(tmp_path)
    spec = specification(target, item, snapshot, variant(target, item), partition(target))
    evidence = passing_evidence()
    evidence[ValidationStageName.WALK_FORWARD.value] = (Decimal("0.10"), Decimal("-0.20"))
    evidence[ValidationStageName.ROBUSTNESS.value] = (Decimal("0.10"), Decimal("-0.10"), Decimal("0.20"))
    evidence[ValidationStageName.SENSITIVITY.value] = (Decimal("0.00"), Decimal("1.00"), Decimal("0.10"))
    result = target.run_validation(spec.experiment_id, evidence)

    reasons = set(result.rejection_reasons)
    assert "WALK_FORWARD_UNSTABLE" in reasons
    assert "ROBUSTNESS_FAILED" in reasons
    assert "SENSITIVITY_TOO_HIGH" in reasons
    assert result.variants_attempted
    assert result.search_space_attempted


def test_recovery_restart_equivalence_lineage_branching_and_rollback(tmp_path):
    target = runtime(tmp_path)
    item, snapshot = candidate(tmp_path)
    plan = partition(target)

    first = variant(target, item)
    first_spec = specification(target, item, snapshot, first, plan)
    first_result = target.run_validation(first_spec.experiment_id, passing_evidence())
    first_promotion = target.assess_promotion(first_result.result_id)
    first_config = target.configurations[first_promotion.approved_research_configuration_id]

    second = target.create_configuration_variant(
        item,
        baseline_configuration_id="CONFIG-A@v3",
        challenger_configuration_id="CONFIG-A-CHALLENGER-002",
        scope="threshold",
        configuration_delta={"strategies.s1_trend_pullback.minimum_adx": 22.0},
        baseline_configuration={"strategies.s1_trend_pullback.minimum_adx": 20.0},
        search_space={"strategies.s1_trend_pullback.minimum_adx": (21.5, 22.0)},
    )
    second_spec = specification(target, item, snapshot, second, plan)
    second_result = target.run_validation(second_spec.experiment_id, passing_evidence())
    second_promotion = target.assess_promotion(second_result.result_id)
    second_config = target.configurations[second_promotion.approved_research_configuration_id]
    rollback = target.rollback_configuration(second_config.research_configuration_id, first_config.research_configuration_id, reason="P50_TEST_ROLLBACK", evidence_refs=(second_promotion.promotion_decision_id,))

    state = target.recovery_state(7)
    fingerprint = target.replay_fingerprint()
    restored = runtime(tmp_path / "restore")
    assert restored.restore(state, 7)
    assert restored.replay_fingerprint() == fingerprint
    assert restored.incremental_equals_full_rebuild()
    assert rollback.to_configuration == first_config.research_configuration_id
    assert first_config.research_configuration_id != second_config.research_configuration_id
    assert len({first_spec.experiment_id, second_spec.experiment_id}) == 2

    bad = replace(state, promotion_policy_identity="OTHER")
    assert restored.restore(bad, 7) is False
    assert restored.recovery_restricted


def test_runtime_diagnostics_and_forbidden_permission_surface(tmp_path):
    target = runtime(tmp_path)
    diagnostics = target.diagnostics()
    forbidden = {
        "deploy_configuration",
        "submit_order",
        "connect_broker",
        "authorize_execution",
        "rewrite_strategy_source",
        "apply_live_configuration",
    }
    assert diagnostics["financial_execution"] == "NONE"
    assert diagnostics["experiment_evidence_sufficiency"] == "NO_EXPERIMENT_EVIDENCE"
    assert forbidden.isdisjoint(set(dir(target)))
