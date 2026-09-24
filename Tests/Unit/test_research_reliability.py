from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from amrte.infrastructure.local import InMemoryAuditSink
from amrte.research.reliability import *


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def initialized(config=None, scope="SCOPE-A", epoch=0, audit=None):
    engine = ResearchReliabilityEngine(config or ReliabilityConfiguration(), audit)
    index = engine.initialize(scope, f"FP-{scope}", NOW, epoch)
    return engine, index


def outcome(tag, delta, at, scope="SCOPE-A", epoch=0, fingerprint=None, available=None):
    return QualityOutcomeDelta.create(scope, delta, at, available or at, f"LIFECYCLE-{tag}", fingerprint or f"FP-{scope}", recovery_epoch=epoch)


def test_configuration_validation():
    with pytest.raises(ValueError):
        ResearchReliabilityEngine(ReliabilityConfiguration(starting_index=Decimal("0")))
    with pytest.raises(ValueError):
        ResearchReliabilityEngine(ReliabilityConfiguration(watch_threshold=Decimal(".2"), restricted_threshold=Decimal(".1")))
    with pytest.raises(ValueError):
        ResearchReliabilityEngine(ReliabilityConfiguration(watch_multiplier=Decimal("1.1")))


def test_initialization_identity_is_deterministic_immutable_and_idempotent():
    engine, first = initialized()
    second = engine.initialize("SCOPE-A", "FP-SCOPE-A", NOW)
    assert first.index_id == second.index_id and len(engine.indices) == 1
    with pytest.raises(FrozenInstanceError):
        first.current_value = Decimal("99")


def test_positive_and_negative_quality_deltas_update_index_and_best_mark():
    engine, index = initialized()
    up = engine.process(outcome("UP", "10", NOW + timedelta(seconds=1)), NOW + timedelta(seconds=1))
    down = engine.process(outcome("DOWN", "-15", NOW + timedelta(seconds=2)), NOW + timedelta(seconds=2))
    assert up.index.current_value == up.index.best_value == Decimal("110")
    assert down.index.current_value == Decimal("95") and down.index.best_value == Decimal("110")
    assert down.index.absolute_deterioration == Decimal("15")


def test_best_mark_is_monotonic_and_cannot_be_lowered():
    engine, _ = initialized()
    values = []
    for i, delta in enumerate(("10", "-30", "5", "40"), 1):
        values.append(engine.process(outcome(str(i), delta, NOW + timedelta(seconds=i)), NOW + timedelta(seconds=i)).index.best_value)
    assert values == sorted(values) and values[-1] == Decimal("125")


@pytest.mark.parametrize("delta,stage,multiplier", [("-4", ReliabilityStage.NORMAL, "1"), ("-5", ReliabilityStage.WATCH, ".75"), ("-10", ReliabilityStage.RESTRICTED, ".50"), ("-15", ReliabilityStage.PROTECTED, ".25"), ("-20", ReliabilityStage.SUSPENDED, "0")])
def test_exact_stage_boundaries_and_non_amplifying_multipliers(delta, stage, multiplier):
    engine, _ = initialized()
    result = engine.process(outcome(delta, delta, NOW + timedelta(seconds=1)), NOW + timedelta(seconds=1))
    assert result.index.raw_stage is stage and result.index.permission_multiplier == Decimal(multiplier)


def test_deterioration_skips_stages_and_restricts_immediately():
    engine, _ = initialized()
    result = engine.process(outcome("FAST", "-30", NOW + timedelta(seconds=1)), NOW + timedelta(seconds=1))
    assert result.index.published_stage is ReliabilityStage.SUSPENDED and result.index.permission_multiplier == 0


def test_recovery_requires_confirmation_and_moves_one_stage_at_a_time():
    engine, _ = initialized(ReliabilityConfiguration(recovery_confirmations=2))
    bad = engine.process(outcome("BAD", "-20", NOW + timedelta(seconds=1)), NOW + timedelta(seconds=1)).index
    first = engine.process(outcome("R1", "10", NOW + timedelta(seconds=2)), NOW + timedelta(seconds=2)).index
    second = engine.process(outcome("R2", "5", NOW + timedelta(seconds=3)), NOW + timedelta(seconds=3)).index
    assert bad.published_stage is ReliabilityStage.SUSPENDED
    assert first.published_stage is ReliabilityStage.SUSPENDED
    assert second.published_stage is ReliabilityStage.PROTECTED


def test_new_best_mark_ends_episode_but_recovery_policy_remains_authoritative():
    engine, _ = initialized(ReliabilityConfiguration(recovery_confirmations=1))
    low = engine.process(outcome("LOW", "-10", NOW + timedelta(seconds=1)), NOW + timedelta(seconds=1)).index
    high = engine.process(outcome("HIGH", "20", NOW + timedelta(seconds=2)), NOW + timedelta(seconds=2)).index
    assert low.episode_started_at_utc is not None
    assert high.episode_started_at_utc is None and high.relative_deterioration == 0 and high.best_value == Decimal("110")


def test_duplicate_future_out_of_order_and_lineage_fail_closed():
    engine, _ = initialized()
    first = outcome("ONE", "-1", NOW + timedelta(seconds=1))
    assert engine.process(first, NOW + timedelta(seconds=1)).decision is ReliabilityDecision.ACCEPTED
    assert engine.process(first, NOW + timedelta(seconds=2)).decision is ReliabilityDecision.NO_ACTION
    future = outcome("FUTURE", "1", NOW + timedelta(seconds=4), available=NOW + timedelta(seconds=5))
    assert engine.process(future, NOW + timedelta(seconds=4)).decision is ReliabilityDecision.BLOCKED
    old = outcome("OLD", "1", NOW)
    assert engine.process(old, NOW + timedelta(seconds=3)).decision is ReliabilityDecision.BLOCKED
    wrong = outcome("WRONG", "1", NOW + timedelta(seconds=3), fingerprint="OTHER")
    assert engine.process(wrong, NOW + timedelta(seconds=3)).decision is ReliabilityDecision.BLOCKED


def test_invalid_numeric_and_missing_source_are_blocked():
    engine, _ = initialized()
    nan = outcome("NAN", Decimal("NaN"), NOW + timedelta(seconds=1))
    assert engine.process(nan, NOW + timedelta(seconds=1)).decision is ReliabilityDecision.BLOCKED
    missing = replace(outcome("MISSING", "1", NOW + timedelta(seconds=1)), source_lifecycle_id="")
    assert engine.process(missing, NOW + timedelta(seconds=1)).decision is ReliabilityDecision.BLOCKED


def test_point_in_time_snapshot_excludes_future_outcomes():
    engine, _ = initialized()
    first_at = NOW + timedelta(seconds=1)
    engine.process(outcome("ONE", "-5", first_at), first_at)
    engine.process(outcome("TWO", "-5", NOW + timedelta(seconds=2)), NOW + timedelta(seconds=2))
    historical = engine.snapshot("SCOPE-A", first_at)
    current = engine.snapshot("SCOPE-A", NOW + timedelta(seconds=2))
    assert historical.current_value == Decimal("95") and len(historical.event_ids) == 1
    assert current.current_value == Decimal("90") and len(current.event_ids) == 2


def test_reconciliation_detects_corruption_and_never_repairs():
    engine, index = initialized()
    result = engine.process(outcome("ONE", "-5", NOW + timedelta(seconds=1)), NOW + timedelta(seconds=1)).index
    assert engine.reconcile("SCOPE-A", NOW + timedelta(seconds=2)).outcome is ReliabilityReconciliationOutcome.CONSISTENT
    engine.indices["SCOPE-A"] = replace(result, current_value=Decimal("999"))
    bad = engine.reconcile("SCOPE-A", NOW + timedelta(seconds=3))
    assert bad.outcome is ReliabilityReconciliationOutcome.FAILED_CLOSED and not bad.repaired


def test_recovery_round_trip_and_replay_fingerprint():
    engine, _ = initialized(epoch=3)
    engine.process(outcome("ONE", "-5", NOW + timedelta(seconds=1), epoch=3), NOW + timedelta(seconds=1))
    fingerprint = engine.replay_fingerprint("SCOPE-A")
    state = engine.recovery_state(3)
    restored = ResearchReliabilityEngine()
    assert restored.restore(state, 3)
    assert restored.replay_fingerprint("SCOPE-A") == fingerprint
    assert restored.indices["SCOPE-A"].current_value == Decimal("95")


def test_incompatible_and_corrupt_recovery_fail_closed():
    engine, _ = initialized(epoch=2)
    state = engine.recovery_state(2)
    target = ResearchReliabilityEngine()
    assert not target.restore(replace(state, recovery_epoch=3), 2) and target.recovery_restricted
    corrupt = replace(state.indices[0], best_value=Decimal("1"))
    target2 = ResearchReliabilityEngine()
    assert not target2.restore(replace(state, indices=(corrupt,)), 2) and target2.recovery_restricted


def test_scope_isolation_bounds_audit_and_trace():
    audit = InMemoryAuditSink()
    engine = ResearchReliabilityEngine(ReliabilityConfiguration(maximum_scopes=2, maximum_events_per_scope=1), audit)
    a = engine.initialize("A", "FP-A", NOW)
    b = engine.initialize("B", "FP-B", NOW)
    result = engine.process(outcome("A1", "-5", NOW + timedelta(seconds=1), scope="A"), NOW + timedelta(seconds=1))
    blocked = engine.process(outcome("A2", "-5", NOW + timedelta(seconds=2), scope="A"), NOW + timedelta(seconds=2))
    assert engine.indices["B"].current_value == b.current_value
    assert blocked.decision is ReliabilityDecision.BLOCKED and result.decision_trace.evaluations
    assert any(item[0] == "reliability_outcome_accepted" for item in audit.events)


def test_metamorphic_worse_outcome_cannot_increase_permission():
    good, _ = initialized()
    bad, _ = initialized()
    good_result = good.process(outcome("G", "-5", NOW + timedelta(seconds=1)), NOW + timedelta(seconds=1)).index
    bad_result = bad.process(outcome("B", "-20", NOW + timedelta(seconds=1)), NOW + timedelta(seconds=1)).index
    assert bad_result.permission_multiplier <= good_result.permission_multiplier


def test_safety_surface_has_no_financial_execution_methods():
    forbidden = {"place_order", "submit_trade", "broker_login", "fill_order", "open_position", "close_position", "set_leverage", "calculate_margin", "account_balance"}
    assert forbidden.isdisjoint(set(dir(ResearchReliabilityEngine())))
