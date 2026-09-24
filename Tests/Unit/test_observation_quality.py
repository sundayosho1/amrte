from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from amrte.infrastructure.local import InMemoryAuditSink
from amrte.research.observation_quality import *


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def observation(index=0, value="10", subject="SUBJECT-A", channel="LATENCY", available=None, health=ObservationHealth.HEALTHY):
    observed = NOW - timedelta(seconds=50 - index)
    return ScalarObservation.create(subject, channel, value, observed, available or observed, "FIXTURE", "DATASET-A", "FINGERPRINT-A", health=health)


def history(values=("9", "10", "10", "10", "11")):
    return tuple(observation(index, value) for index, value in enumerate(values))


def test_configuration_validation_and_threshold_order():
    with pytest.raises(ValueError):
        ObservationQualityEngine(QualityConfiguration(minimum_baseline_samples=1))
    with pytest.raises(ValueError):
        ObservationQualityEngine(QualityConfiguration(elevated_ratio=Decimal("2"), high_ratio=Decimal("1.5")))
    with pytest.raises(ValueError):
        ObservationQualityEngine(QualityConfiguration(degraded_multiplier=Decimal("1.1")))


def test_observation_identity_is_deterministic_and_immutable():
    one = observation()
    two = observation()
    assert one.observation_id == two.observation_id
    with pytest.raises(FrozenInstanceError):
        one.value = Decimal("12")


def test_robust_baseline_median_mad_percentile_and_lineage():
    engine = ObservationQualityEngine()
    baseline = engine.build_baseline(history(("1", "9", "10", "11", "100")), NOW)
    assert baseline.median_value == Decimal("10")
    assert baseline.median_absolute_deviation == Decimal("1")
    assert baseline.sample_count == 5
    assert baseline.percentile_90 == Decimal("64.4")
    assert baseline.source_observation_ids


def test_insufficient_mixed_or_unhealthy_baseline_fails_closed():
    engine = ObservationQualityEngine()
    assert engine.build_baseline(history(("9", "10")), NOW) is None
    mixed = history() + (observation(8, "10", subject="OTHER"),)
    assert engine.build_baseline(mixed, NOW) is None
    unhealthy = history()[:-1] + (observation(8, "10", health=ObservationHealth.DEGRADED),)
    assert engine.build_baseline(unhealthy, NOW) is None


def test_future_observations_are_excluded_from_baseline():
    engine = ObservationQualityEngine()
    future = observation(9, "999", available=NOW + timedelta(seconds=1))
    baseline = engine.build_baseline(history() + (future,), NOW)
    assert baseline.sample_count == 5 and baseline.median_value == Decimal("10")


@pytest.mark.parametrize("value,expected", [("14", DeviationRegime.NORMAL), ("15", DeviationRegime.ELEVATED), ("20", DeviationRegime.HIGH), ("30", DeviationRegime.EXTREME)])
def test_deviation_regimes(value, expected):
    engine = ObservationQualityEngine()
    baseline = engine.build_baseline(history(), NOW)
    result = engine.analyze(observation(20, value), baseline, NOW)
    assert result.regime is expected and Decimal("0") <= result.percentile_rank <= Decimal("1")


def test_zero_baseline_has_explicit_unknown_ratio_without_division_error():
    engine = ObservationQualityEngine()
    baseline = engine.build_baseline(history(("0", "0", "0", "0", "0")), NOW)
    result = engine.analyze(observation(20, "1"), baseline, NOW)
    assert result.relative_ratio is None and result.regime is DeviationRegime.UNKNOWN


def test_quality_states_and_non_amplifying_restrictions():
    engine = ObservationQualityEngine()
    healthy = engine.evaluate(observation(20, "10"), history(), NOW)
    degraded = engine.evaluate(observation(21, "15"), history(), NOW + timedelta(seconds=1))
    poor = engine.evaluate(observation(22, "20"), history(), NOW + timedelta(seconds=2))
    assert healthy.restriction_multiplier == 1
    assert degraded.restriction_multiplier <= healthy.restriction_multiplier
    assert poor.restriction_multiplier <= degraded.restriction_multiplier


def test_missing_baseline_and_stale_data_block():
    engine = ObservationQualityEngine(QualityConfiguration(maximum_age_seconds=10))
    missing = engine.evaluate(observation(), (), NOW)
    stale = engine.evaluate(observation(), history(), NOW)
    assert missing.restriction is ResearchRestriction.BLOCK
    assert stale.raw_state is ResearchQualityState.UNAVAILABLE and stale.restriction is ResearchRestriction.BLOCK


def test_future_current_observation_is_untrusted():
    engine = ObservationQualityEngine(max_age_config())
    current = observation(20, "10", available=NOW + timedelta(seconds=1))
    result = engine.evaluate(current, history(), NOW)
    assert result.raw_state is ResearchQualityState.UNTRUSTED and result.restriction is ResearchRestriction.BLOCK


def max_age_config(**changes):
    values = dict(maximum_age_seconds=3600)
    values.update(changes)
    return QualityConfiguration(**values)


def test_restrict_fast_recover_slow_hysteresis():
    engine = ObservationQualityEngine(max_age_config(recovery_confirmations=2, repeated_failure_limit=9))
    bad = engine.evaluate(observation(20, "30"), history(), NOW)
    first = engine.evaluate(observation(21, "10"), history(), NOW + timedelta(seconds=1))
    second = engine.evaluate(observation(22, "10"), history(), NOW + timedelta(seconds=2))
    assert bad.published_state is ResearchQualityState.UNTRUSTED
    assert first.published_state is ResearchQualityState.UNTRUSTED
    assert second.published_state is ResearchQualityState.HEALTHY


def test_repeated_failures_escalate_and_never_increase_permission():
    engine = ObservationQualityEngine(max_age_config(repeated_failure_limit=2))
    first = engine.evaluate(observation(20, "20"), history(), NOW)
    second = engine.evaluate(observation(21, "20"), history(), NOW + timedelta(seconds=1))
    assert first.restriction_multiplier <= 1
    assert second.published_state is ResearchQualityState.UNTRUSTED and second.restriction_multiplier == 0


def test_subject_channel_and_configuration_isolation():
    engine = ObservationQualityEngine(max_age_config())
    first = engine.evaluate(observation(20, "30", subject="A"), tuple(observation(i, "10", subject="A") for i in range(5)), NOW)
    second = engine.evaluate(observation(20, "10", subject="B"), tuple(observation(i, "10", subject="B") for i in range(5)), NOW)
    assert first.restriction is ResearchRestriction.BLOCK
    assert second.restriction is ResearchRestriction.ALLOW
    baseline = engine.build_baseline(history(), NOW)
    wrong = replace(observation(20, "10"), configuration_snapshot_id="OTHER")
    assert engine.analyze(wrong, baseline, NOW).health is ObservationHealth.INVALID
    wrong_dataset = replace(observation(20, "10"), dataset_fingerprint="OTHER")
    assert engine.analyze(wrong_dataset, baseline, NOW).health is ObservationHealth.INVALID


def test_neutral_workflow_health_integration_is_attributable_and_non_amplifying():
    engine = ObservationQualityEngine(max_age_config())
    degraded = WorkflowQualityEvidence.create("WORKFLOW-SNAPSHOT", "SUBJECT-A", 1, ObservationHealth.DEGRADED, NOW)
    result = engine.evaluate(observation(20, "10"), history(), NOW, workflow_evidence=degraded)
    assert result.raw_state is ResearchQualityState.DEGRADED and result.restriction_multiplier < 1
    invalid = WorkflowQualityEvidence.create("WORKFLOW-SNAPSHOT-2", "OTHER", 1, ObservationHealth.HEALTHY, NOW)
    blocked = ObservationQualityEngine(max_age_config()).evaluate(observation(20, "10"), history(), NOW, workflow_evidence=invalid)
    assert blocked.restriction is ResearchRestriction.BLOCK


def test_snapshot_identity_replay_and_trace_are_deterministic():
    config = max_age_config()
    a = ObservationQualityEngine(config).evaluate(observation(20, "10"), history(), NOW)
    b = ObservationQualityEngine(config).evaluate(observation(20, "10"), tuple(reversed(history())), NOW)
    assert a.snapshot_id == b.snapshot_id
    assert a.decision_trace.evaluations[0].input_references


def test_recovery_round_trip_and_incompatible_state_fail_closed():
    engine = ObservationQualityEngine(max_age_config())
    result = engine.evaluate(observation(20, "10"), history(), NOW, recovery_epoch=4)
    state = engine.recovery_state(4)
    restored = ObservationQualityEngine(max_age_config())
    assert restored.restore(state, 4)
    assert next(iter(restored.latest.values())).snapshot_id == result.snapshot_id
    assert not restored.restore(replace(state, recovery_epoch=5), 4) and restored.recovery_restricted


def test_corrupt_recovery_multiplier_and_duplicate_snapshot_fail_closed():
    engine = ObservationQualityEngine(max_age_config())
    result = engine.evaluate(observation(20, "10"), history(), NOW, recovery_epoch=1)
    state = engine.recovery_state(1)
    bad_snapshot = replace(result, restriction_multiplier=Decimal("2"))
    target = ObservationQualityEngine(max_age_config())
    assert not target.restore(replace(state, latest_snapshots=(bad_snapshot,)), 1)
    target2 = ObservationQualityEngine(max_age_config())
    assert not target2.restore(replace(state, latest_snapshots=(result, result)), 1)


def test_bounded_history_audit_and_no_system_clock_dependency():
    audit = InMemoryAuditSink()
    engine = ObservationQualityEngine(max_age_config(maximum_history_per_scope=2, maximum_snapshots=2), audit)
    for index in range(4):
        engine.evaluate(observation(20 + index, "10"), history(), NOW + timedelta(seconds=index))
    assert len(next(iter(engine.histories.values()))) == 2 and len(engine.snapshots) == 2
    assert any(event[0] == "research_quality_evaluated" for event in audit.events)


def test_safety_surface_has_no_financial_or_execution_methods():
    names = set(dir(ObservationQualityEngine()))
    forbidden = {"place_order", "broker_login", "connect_broker", "fill_order", "calculate_margin", "set_leverage", "open_position", "close_position", "submit_trade"}
    assert forbidden.isdisjoint(names)


def test_metamorphic_worse_observation_cannot_improve_restriction():
    good = ObservationQualityEngine(max_age_config()).evaluate(observation(20, "10"), history(), NOW)
    worse = ObservationQualityEngine(max_age_config()).evaluate(observation(20, "30"), history(), NOW)
    assert worse.restriction_multiplier <= good.restriction_multiplier
