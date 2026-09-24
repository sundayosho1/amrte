from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

import pytest

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.models import (
    BarState, DataHealth, DataValidity, MarketDataSnapshot, NormalizedBar,
    SpreadHealth, SpreadOrigin, SpreadState, SynchronizationStatus,
)
from amrte.market.structure import (
    Alignment, BreakConfirmation, ConsolidationState, MarketStructureEngine,
    ShiftStatus, StructureConfiguration, StructureHealth, StructuralDirection,
    SwingClass, SwingStatus, SwingType, TiePolicy, ZoneState, ZoneType,
)

UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)


def bars(values, timeframe="M15"):
    result = []
    for i, value in enumerate(values):
        opening = START + timedelta(minutes=15*i)
        result.append(NormalizedBar("FICTIONAL_ALPHA", timeframe, opening,
            opening + timedelta(minutes=15), value, value+1, value-1, value+.25,
            bar_state=BarState.CLOSED_BAR, validity=DataValidity.VALID,
            source_reference=str(i), bar_id=f"{timeframe}-{i}"))
    return tuple(result)


def snapshot(series, *, health=DataHealth.HEALTHY,
             synchronization=SynchronizationStatus.SYNCHRONIZED):
    spread = SpreadState(None, None, None, None, None, SpreadHealth.UNAVAILABLE, SpreadOrigin.UNAVAILABLE)
    return MarketDataSnapshot("MD-1", START, series[-1].close_time, "EXP", "DS", "FP",
        "FICTIONAL_ALPHA", spread, series, series, series, synchronization, health, 100.0,
        {}, "CFG", 0)


def engine(**changes):
    config = StructureConfiguration(**changes)
    return MarketStructureEngine(FixedClock(START + timedelta(days=1)), InMemoryAuditSink(), config)


def test_configuration_rejects_invalid_values():
    with pytest.raises(ValueError): engine(left_bars=0)
    with pytest.raises(ValueError): engine(consolidation_entry_threshold=.2, consolidation_exit_threshold=.1)
    with pytest.raises(ValueError): engine(alignment_weights=(0, 0, 0))


def test_swing_candidates_and_confirmation_timestamp_prevent_early_exposure():
    e = engine(left_bars=1, right_bars=2)
    incomplete = bars((1, 4, 2))
    candidate = e.swing_candidates(incomplete, dataset_id="DS", snapshot_id="MD")[0]
    assert candidate.swing_type is SwingType.SWING_HIGH
    assert candidate.status is SwingStatus.SWING_CANDIDATE and candidate.confirmed_at is None
    complete = bars((1, 4, 2, 1))
    confirmed = e.swing_candidates(complete, dataset_id="DS", snapshot_id="MD")[0]
    assert confirmed.status is SwingStatus.CONFIRMED_SWING
    assert confirmed.confirmed_at == complete[3].close_time
    assert confirmed.confirmation_bar_id == complete[3].bar_id
    assert confirmed.swing_id == candidate.swing_id


def test_swing_high_low_and_deterministic_identity():
    e = engine(left_bars=1, right_bars=1)
    series = bars((2, 5, 2, 1, 4))
    first = e.swing_candidates(series, dataset_id="DS", snapshot_id="MD")
    second = e.swing_candidates(series, dataset_id="DS", snapshot_id="MD")
    assert {s.swing_type for s in first} >= {SwingType.SWING_HIGH, SwingType.SWING_LOW}
    assert tuple(s.swing_id for s in first) == tuple(s.swing_id for s in second)


@pytest.mark.parametrize("policy", list(TiePolicy))
def test_tie_policies_are_deterministic(policy):
    e = engine(left_bars=1, right_bars=1, tie_policy=policy)
    result = e.swing_candidates(bars((2, 2, 2)), dataset_id="DS", snapshot_id="MD")
    if policy is TiePolicy.REJECT_AMBIGUOUS: assert result == ()
    else: assert result


def test_first_and_last_plateau_policies_select_different_deterministic_bars():
    series = bars((1, 4, 4, 2))
    first = engine(left_bars=1, right_bars=1, tie_policy=TiePolicy.FIRST).swing_candidates(series, dataset_id="DS", snapshot_id="MD")
    last = engine(left_bars=1, right_bars=1, tie_policy=TiePolicy.LAST).swing_candidates(series, dataset_id="DS", snapshot_id="MD")
    first_high = next(item for item in first if item.swing_type is SwingType.SWING_HIGH)
    last_high = next(item for item in last if item.swing_type is SwingType.SWING_HIGH)
    assert first_high.bar_id != last_high.bar_id


def test_relative_hh_lh_hl_ll_and_equal_classification():
    e = engine(left_bars=1, right_bars=1, equality_tolerance=.01)
    raw = e.swing_candidates(bars((2,5,2,3,6,4,2,5,1,4,1.005,3)), dataset_id="DS", snapshot_id="MD")
    classified = e.classify_swings(raw)
    classes = {item.relative_classification for item in classified}
    assert SwingClass.HIGHER_HIGH in classes
    assert SwingClass.LOWER_HIGH in classes
    assert SwingClass.HIGHER_LOW in classes or SwingClass.LOWER_LOW in classes
    assert SwingClass.EQUAL_LOW in classes or SwingClass.EQUAL_HIGH in classes


def _classified(kind, classifications):
    from amrte.market.structure import StructuralSwing
    return tuple(StructuralSwing(f"S{i}", "I", "M15", kind if i%2==0 else
        (SwingType.SWING_LOW if kind is SwingType.SWING_HIGH else SwingType.SWING_HIGH),
        10+i, f"B{i}", START, START, START, f"C{i}", classification,
        SwingStatus.CONFIRMED_SWING, 1, 100, "DS", "MD")
        for i, classification in enumerate(classifications))


@pytest.mark.parametrize(("classes","expected"), [
    ((SwingClass.HIGHER_HIGH, SwingClass.HIGHER_LOW), StructuralDirection.BULLISH),
    ((SwingClass.LOWER_HIGH, SwingClass.LOWER_LOW), StructuralDirection.BEARISH),
    ((SwingClass.EQUAL_HIGH, SwingClass.EQUAL_LOW), StructuralDirection.SIDEWAYS),
    ((SwingClass.HIGHER_HIGH, SwingClass.LOWER_LOW), StructuralDirection.MIXED),
    ((SwingClass.UNCLASSIFIED,), StructuralDirection.UNKNOWN),
])
def test_structural_direction_semantics(classes, expected):
    direction, _ = engine(minimum_structural_evidence=1).direction(_classified(SwingType.SWING_HIGH, classes))
    assert direction is expected


def test_close_bos_requires_close_and_minimum_penetration():
    e = engine(left_bars=1, right_bars=1, break_confirmation=BreakConfirmation.CLOSE_BREAK,
               minimum_penetration=.5)
    series = bars((2,5,2,4,5.1,7))
    swings = e.classify_swings(e.swing_candidates(series, dataset_id="DS", snapshot_id="MD"))
    events = e.breaks(series, swings, snapshot(series))
    assert events and all(item.penetration > .5 for item in events)
    assert len({item.break_id for item in events}) == len(events)


def test_wick_and_close_break_policies_differ():
    base = list(bars((2,5,2,4)))
    base[-1] = replace(base[-1], high=7, close=4)
    snap = snapshot(tuple(base))
    wick = engine(left_bars=1, right_bars=1, break_confirmation=BreakConfirmation.WICK_BREAK)
    close = engine(left_bars=1, right_bars=1, break_confirmation=BreakConfirmation.CLOSE_BREAK)
    ws = wick.classify_swings(wick.swing_candidates(tuple(base), dataset_id="DS", snapshot_id="MD"))
    cs = close.classify_swings(close.swing_candidates(tuple(base), dataset_id="DS", snapshot_id="MD"))
    assert wick.breaks(tuple(base), ws, snap)
    assert not close.breaks(tuple(base), cs, snap)


def test_structural_shift_requires_opposing_confirmed_break():
    e = engine(left_bars=1, right_bars=1)
    series = bars((2,5,2,4,6))
    swings = e.classify_swings(e.swing_candidates(series, dataset_id="DS", snapshot_id="MD"))
    breaks = e.breaks(series, swings, snapshot(series))
    shifts = e.shifts(StructuralDirection.BEARISH, breaks, snapshot(series))
    assert shifts and all(item.status is ShiftStatus.CONFIRMED_SHIFT for item in shifts)


def test_consolidation_unknown_consolidating_and_not_consolidating():
    assert engine(consolidation_window=5).consolidation(bars((1,2))).state is ConsolidationState.UNKNOWN
    flat = bars((100,100.1,100,100.1,100))
    assert engine(consolidation_window=5).consolidation(flat).state is ConsolidationState.CONSOLIDATING
    wide = bars((100,120,90,130,80))
    assert engine(consolidation_window=5).consolidation(wide).state is ConsolidationState.NOT_CONSOLIDATING


def test_consolidation_hysteresis_retains_state_between_entry_and_exit_thresholds():
    e = engine(consolidation_window=4, consolidation_entry_threshold=.03,
               consolidation_exit_threshold=.08)
    series = bars((100,100.1,100,100.1,104))
    assert e.consolidation(series).state is ConsolidationState.CONSOLIDATING


def test_zone_creation_bounds_tests_breaks_merging_and_limits():
    e = engine(left_bars=1, right_bars=1, zone_width_percentage=.01,
               zone_merge_threshold=.02, maximum_active_zones=2)
    series = bars((2,5,2,5.01,2,6,1))
    swings = e.classify_swings(e.swing_candidates(series, dataset_id="DS", snapshot_id="MD"))
    zones = e.zones(swings, series, "DS")
    assert len(zones) <= 2
    assert all(zone.lower_bound < zone.upper_bound and zone.source_swing_ids for zone in zones)
    assert any(zone.zone_type in (ZoneType.SUPPORT, ZoneType.RESISTANCE) for zone in zones)
    assert any(zone.state in (ZoneState.TESTED, ZoneState.BROKEN, ZoneState.ACTIVE) for zone in zones)


def test_invalid_and_unsynchronized_market_snapshots_are_rejected():
    series = bars((1,3,1,4,2,5,3))
    assert engine(left_bars=1, right_bars=1).analyze(snapshot(series, health=DataHealth.INVALID)) is None
    assert engine(left_bars=1, right_bars=1).analyze(snapshot(series, synchronization=SynchronizationStatus.UNSYNCHRONIZED)) is None


def test_structure_snapshot_lineage_immutability_cache_and_rebuild_equivalence():
    series = bars((1,3,1,4,2,5,3,6,4,7,5))
    e = engine(left_bars=1, right_bars=1, minimum_structural_evidence=1)
    source = snapshot(series)
    first = e.analyze(source, configuration_hash="HASH")
    cached = e.analyze(source, configuration_hash="HASH")
    rebuilt = e.rebuild(source, configuration_hash="HASH")
    assert first == cached == rebuilt
    assert first.source_market_data_snapshot_id == source.snapshot_id
    assert first.structure_snapshot_id == rebuilt.structure_snapshot_id
    with pytest.raises(FrozenInstanceError): first.alignment = Alignment.UNKNOWN


def test_cache_isolation_and_invalidation():
    series = bars((1,3,1,4,2,5,3,6,4))
    e = engine(left_bars=1, right_bars=1, minimum_structural_evidence=1)
    source = snapshot(series)
    one = e.analyze(source, configuration_hash="A")
    two = e.analyze(source, configuration_hash="B")
    assert one.structure_snapshot_id != two.structure_snapshot_id
    assert e.invalidate_cache() == 2


def test_alignment_matrix_unknown_full_partial_conflicting_and_neutral():
    e = engine()
    def tf(direction, health=StructureHealth.HEALTHY):
        from amrte.market.structure import ConfidenceResult, ConsolidationResult, TimeframeStructure
        return TimeframeStructure("M15", START, DataHealth.HEALTHY, health, direction, (), (), (),
            ConsolidationResult(ConsolidationState.UNKNOWN,None,None,None,None,None,0,()), (),
            ConfidenceResult(80, {"x":80}, (), 2, health), ())
    assert e.alignment((tf(StructuralDirection.BULLISH),)*3)[0] is Alignment.FULL_BULLISH_ALIGNMENT
    assert e.alignment((tf(StructuralDirection.BEARISH),)*3)[0] is Alignment.FULL_BEARISH_ALIGNMENT
    assert e.alignment((tf(StructuralDirection.BULLISH),tf(StructuralDirection.BULLISH),tf(StructuralDirection.SIDEWAYS)))[0] is Alignment.PARTIAL_BULLISH_ALIGNMENT
    assert e.alignment((tf(StructuralDirection.BEARISH),tf(StructuralDirection.BEARISH),tf(StructuralDirection.SIDEWAYS)))[0] is Alignment.PARTIAL_BEARISH_ALIGNMENT
    assert e.alignment((tf(StructuralDirection.BULLISH),tf(StructuralDirection.BEARISH),tf(StructuralDirection.BULLISH)))[0] is Alignment.CONFLICTING
    assert e.alignment((tf(StructuralDirection.SIDEWAYS),)*3)[0] is Alignment.NEUTRAL
    assert e.alignment((tf(StructuralDirection.UNKNOWN),)*3)[0] is Alignment.UNKNOWN
    assert e.alignment((tf(StructuralDirection.BULLISH, StructureHealth.INVALID_INPUT),)*3)[0] is Alignment.UNKNOWN


def test_confidence_cannot_override_invalid_or_insufficient_health():
    series = bars((1,2,1))
    result = engine(left_bars=1, right_bars=1).analyze(snapshot(series))
    assert result.overall_structure_health is StructureHealth.INSUFFICIENT_HISTORY
    assert result.overall_confidence.score == 0
    assert not engine().readiness(result)[0]


def test_recovery_state_is_compact_and_deduplicated():
    series = bars((1,3,1,4,2,5,3,6,4))
    e = engine(left_bars=1, right_bars=1, minimum_structural_evidence=1)
    e.analyze(snapshot(series))
    state = e.recovery_state()
    assert "historical_bars" not in state
    assert len(state["emitted_break_ids"]) == len(set(state["emitted_break_ids"]))
