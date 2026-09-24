from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.research.controlled_experimentation import ControlledResearchExperimentRuntime, PromotionDecisionValue, ValidationStageName
from amrte.research.improvement_intelligence import FindingType
from Tests.Unit.test_events import NOW
from Tests.Unit.test_research_improvement_intelligence import analyze, p48_evidence, runtime as p49_runtime


def test_prompt50_synthetic_experiment_workload_is_bounded(tmp_path):
    p49 = p49_runtime(tmp_path / "p49", max_items=512)
    snapshot, attributions = p48_evidence(
        tmp_path,
        tuple((-5 if i % 2 else 5) for i in range(1, 41)),
        mutate=lambda i, a: replace(a, strategy_id="S1" if i % 2 else "S2"),
    )
    analyze(p49, snapshot, attributions)
    candidate = next(item for item in p49.candidates.values() if item.finding_type == FindingType.STRATEGY_DEGRADATION.value)
    target = ControlledResearchExperimentRuntime(
        clock=FixedClock(NOW + timedelta(hours=3)),
        audit=InMemoryAuditSink(),
        storage_root=tmp_path / "p50",
        maximum_experiments=64,
        maximum_configurations=64,
    )
    plan = target.create_partition_plan(
        dataset_id="P50-PERF-DATASET",
        dataset_fingerprint="P50-PERF-FP",
        source_identity="P50-PERF-SOURCE",
        instrument="AMRTE.TEST",
        timeframe="M15",
        coverage_start=NOW,
        coverage_end=NOW + timedelta(days=20),
    )
    evidence = {
        ValidationStageName.HISTORICAL.value: (Decimal("0.2"), Decimal("0.2"), Decimal("0.2")),
        ValidationStageName.OUT_OF_SAMPLE.value: (Decimal("0.1"), Decimal("0.1"), Decimal("0.1")),
        ValidationStageName.WALK_FORWARD.value: (Decimal("0.1"), Decimal("0.1")),
        ValidationStageName.ROBUSTNESS.value: (Decimal("0.1"), Decimal("0.1"), Decimal("0.1")),
        ValidationStageName.SENSITIVITY.value: (Decimal("0.1"), Decimal("0.11"), Decimal("0.09")),
    }

    for index in range(24):
        variant = target.create_configuration_variant(
            candidate,
            baseline_configuration_id="CONFIG-PERF@v1",
            challenger_configuration_id=f"CONFIG-PERF-CHALLENGER-{index:03d}",
            scope="threshold",
            configuration_delta={"strategies.s1_trend_pullback.minimum_adx": 20.0 + (index % 4)},
            baseline_configuration={"strategies.s1_trend_pullback.minimum_adx": 20.0},
            search_space={"strategies.s1_trend_pullback.minimum_adx": (20.0, 21.0, 22.0, 23.0)},
        )
        spec = target.register_experiment(candidate, source_improvement_snapshot_id=snapshot.snapshot_id, variant=variant, partition_plan=plan, software_release_identity="P50-PERF")
        result = target.run_validation(spec.experiment_id, evidence)
        promotion = target.assess_promotion(result.result_id)
        assert promotion.decision == PromotionDecisionValue.APPROVE_RESEARCH_CONFIGURATION.value

    diagnostics = target.diagnostics()
    assert diagnostics["experiment_count"] == 24
    assert diagnostics["approved_research_configuration_count"] == 24
    assert diagnostics["memory"]["experiments"] <= diagnostics["memory"]["experiment_limit"]
    assert target.incremental_equals_full_rebuild()
