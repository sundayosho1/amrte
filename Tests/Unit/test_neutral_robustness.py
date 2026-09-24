from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from amrte.infrastructure.local import InMemoryAuditSink
from amrte.validation.experiments import NeutralObservation
from amrte.validation.robustness import *

NOW = datetime(2026, 9, 21, tzinfo=timezone.utc)


def observations(count=80, delta=Decimal("0")):
    return tuple(NeutralObservation.create(
        f"S{i % 4}", f"C{i % 3}", f"X{i % 2}", NOW + timedelta(hours=i),
        NOW + timedelta(hours=i), Decimal(i % 7) / Decimal("10") + delta, "FP")
        for i in range(count))


def plan(**changes):
    handoff = ResearchValidationHandoff("EXP", "FP", ("P0", "P1", "P2"), "REPLAY", 80, "CFG")
    values = dict(handoff=handoff, mode=ValidationMode.PRE_REGISTERED,
                  window_mode=WindowMode.ROLLING, coverage_start_utc=NOW,
                  coverage_end_utc=NOW + timedelta(hours=80),
                  development_duration=timedelta(hours=20), validation_duration=timedelta(hours=10),
                  step=timedelta(hours=10), embargo=timedelta(0), frozen_parameter_set_id="P0",
                  resampling_method=ResamplingMethod.BLOCK, resampling_iterations=50,
                  seed=42, block_size=3, stress_decrements=(Decimal(".1"), Decimal(".2")),
                  configuration_snapshot_id="CFG", registered_at_utc=NOW - timedelta(seconds=1))
    values.update(changes)
    return RobustnessValidationPlan.create(**values)


def engine():
    return DeterministicRobustnessEngine(RobustnessConfiguration(
        minimum_sample=3, minimum_windows=2, configuration_snapshot_id="CFG"))


def prepared(**changes):
    target = engine(); p = plan(**changes); assert target.register(p, observations())[0]
    return target, p


def seal_all(target, p):
    return target.seal_holdout(p.plan_id, NOW + timedelta(hours=20),
                               NOW + timedelta(hours=80), NOW + timedelta(hours=19))


def test_plan_identity_immutability_and_changed_policy():
    p = plan(); assert p.plan_id == plan().plan_id and p.plan_id != plan(seed=43).plan_id
    with pytest.raises(FrozenInstanceError): p.seed = 4


def test_invalid_configuration_and_plan_fail_closed():
    with pytest.raises(ValueError): DeterministicRobustnessEngine(RobustnessConfiguration(maximum_windows=0))
    target = engine(); bad = plan(resampling_iterations=10001)
    assert not target.register(bad, observations())[0]


def test_future_known_and_wrong_lineage_observations_rejected():
    p = plan(); target = engine()
    future = NeutralObservation.create("S", "C", "X", NOW, NOW + timedelta(days=10), 1, "FP")
    wrong = NeutralObservation.create("S", "C", "X", NOW, NOW, 1, "OTHER")
    assert not target.register(p, (future, wrong))[0]


@pytest.mark.parametrize("mode", [WindowMode.ROLLING, WindowMode.ANCHORED])
def test_deterministic_nonoverlapping_windows_and_embargo(mode):
    target, p = prepared(window_mode=mode, embargo=timedelta(hours=2))
    a = target.generate_windows(p.plan_id); b = target.generate_windows(p.plan_id)
    assert a == b and a and all(x.development_end_utc < x.validation_start_utc for x in a)
    if mode is WindowMode.ANCHORED: assert len({x.development_start_utc for x in a}) == 1


def test_holdout_seal_and_contamination_veto():
    target, p = prepared(); target.seal_holdout(p.plan_id, NOW + timedelta(hours=20),
                                                NOW + timedelta(hours=80), NOW + timedelta(hours=30))
    result = target.run(p.plan_id, NOW + timedelta(hours=80))
    assert target.profiles[result.profile_id].classification is RobustnessClassification.CONTAMINATED


def test_clean_holdout_reuse_becomes_potentially_contaminated():
    target, p = prepared(); seal_all(target, p)
    first = target.run(p.plan_id, NOW + timedelta(hours=80)); second = target.run(p.plan_id, NOW + timedelta(hours=81))
    assert target.profiles[first.profile_id].contamination is ContaminationState.CLEAN
    assert target.profiles[second.profile_id].contamination is ContaminationState.POTENTIALLY_CONTAMINATED


@pytest.mark.parametrize("method", list(ResamplingMethod))
def test_seeded_resampling_is_reproducible_and_bounded(method):
    target, p = prepared(resampling_method=method)
    values = tuple(Decimal(i) for i in range(10))
    assert target.resample(p.plan_id, values) == target.resample(p.plan_id, values)
    assert target.resample(p.plan_id, values).count == p.resampling_iterations


def test_different_seed_changes_distribution_identity():
    a, pa = prepared(seed=1); b, pb = prepared(seed=2)
    values = tuple(Decimal(i) for i in range(10))
    assert a.resample(pa.plan_id, values) != b.resample(pb.plan_id, values)


def test_stress_is_monotonic_and_original_immutable():
    target = engine(); original = (Decimal("1"), Decimal("2"))
    stressed = target.stress(original, Decimal(".5"))
    assert original == (Decimal("1"), Decimal("2")) and all(a <= b for a, b in zip(stressed, original))
    with pytest.raises(ValueError): target.stress(original, Decimal("-1"))


def test_parameter_cliff_plateau_and_isolated_peak():
    target = engine()
    cliff = target.parameter_robustness(("A", "B", "C"), (Decimal("0"), Decimal("2")))
    plateau = target.parameter_robustness(("A", "B"), (Decimal("1"), Decimal("1.1")))
    assert cliff.cliff_detected and cliff.isolated_peak and plateau.plateau_detected


def test_end_to_end_profile_evidence_trace_and_reconciliation():
    audit = InMemoryAuditSink(); target = DeterministicRobustnessEngine(
        RobustnessConfiguration(minimum_sample=3, minimum_windows=2, configuration_snapshot_id="CFG"), audit)
    p = plan(); assert target.register(p, observations())[0]; seal_all(target, p)
    result = target.run(p.plan_id, NOW + timedelta(hours=80)); trace = target.trace(result.result_id, NOW + timedelta(hours=81))
    assert result.evidence_ids and trace.evaluations and target.reconcile(p.plan_id) == (True, ())
    assert any(x[0] == "robustness_classified" for x in audit.events)


def test_unfavorable_window_is_preserved():
    target, p = prepared(); seal_all(target, p); result = target.run(p.plan_id, NOW + timedelta(hours=80))
    assert len(result.window_result_ids) == len(target.window_results)


def test_recovery_replay_and_incompatible_epoch():
    target, p = prepared(); seal_all(target, p); result = target.run(p.plan_id, NOW + timedelta(hours=80))
    state = target.recovery_state(4); restored = engine(); assert restored.restore(state, 4)
    assert restored.results[result.result_id] == result and restored.replay_fingerprint(p.plan_id) == result.replay_fingerprint
    assert not engine().restore(replace(state, recovery_epoch=5), 4)


def test_concurrent_equivalent_run_is_idempotent():
    target, p = prepared(); seal_all(target, p)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: target.run(p.plan_id, NOW + timedelta(hours=80)), range(4)))
    assert len({x.result_id for x in results}) == 1


def test_reconciliation_detects_overlap_without_mutation():
    target, p = prepared(); window = target.generate_windows(p.plan_id)[0]
    target.windows[window.window_id] = replace(window, validation_start_utc=window.development_end_utc - timedelta(seconds=1))
    assert target.reconcile(p.plan_id)[0] is False


def test_preregistration_and_zero_window_evidence():
    invalid = plan(registered_at_utc=NOW + timedelta(seconds=1)); assert not engine().register(invalid, observations())[0]
    target = engine(); p = plan(coverage_end_utc=NOW + timedelta(hours=25)); assert target.register(p, observations(25))[0]
    seal = target.seal_holdout(
        p.plan_id, NOW + timedelta(hours=20), NOW + timedelta(hours=25), NOW + timedelta(hours=19))
    result = target.run(p.plan_id, NOW + timedelta(hours=25))
    assert target.profiles[result.profile_id].classification is RobustnessClassification.INSUFFICIENT_EVIDENCE


def test_engine_exposes_no_financial_or_wagering_operations():
    forbidden = {"place_order", "submit_trade", "open_position", "close_position", "broker_login",
                 "set_leverage", "calculate_margin", "wager", "bet", "optimize_profit"}
    assert forbidden.isdisjoint(dir(DeterministicRobustnessEngine))
