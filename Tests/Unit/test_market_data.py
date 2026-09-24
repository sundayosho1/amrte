from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.cache import BoundedMarketDataCache, CacheKey
from amrte.market.models import (
    AdmissionStatus, AnomalyClassification, BarState, DataHealth, DataValidity,
    InstrumentMetadata, NormalizedBar, ProviderCapability, SpreadHealth, SpreadOrigin,
    VolumeKind,
)
from amrte.market.provider import DeterministicMarketDataProvider, dataset_fingerprint
from amrte.market.service import MarketDataService, deterministic_bar_id

UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)


def bar(index=0, timeframe="M15", **changes):
    opening = START + timedelta(minutes=15 * index)
    values = dict(instrument_id="FICTIONAL_ALPHA", timeframe=timeframe,
                  open_time=opening, close_time=opening + timedelta(minutes=15),
                  open=100.0 + index, high=102.0 + index, low=99.0 + index,
                  close=101.0 + index, tick_volume=10.0, real_volume=None,
                  spread=0.2, bar_state=BarState.CLOSED_BAR,
                  validity=DataValidity.UNKNOWN, source_reference=f"row-{index}",
                  volume_kind=VolumeKind.TICK_VOLUME)
    values.update(changes)
    return NormalizedBar(**values)


def provider(bars=None, available=True):
    items = tuple(bars if bars is not None else (bar(0), bar(1), bar(2)))
    metadata = InstrumentMetadata("FICTIONAL_ALPHA", "SYN_ALPHA", precision=4,
        tick_size=.0001, supported_timeframes=("M15", "H1", "H4"),
        capabilities=frozenset({ProviderCapability.BAR_DATA, ProviderCapability.SPREAD_DATA,
                                ProviderCapability.VOLUME_DATA}))
    return DeterministicMarketDataProvider("OFFLINE-1", "DATASET-1", "1", items, (metadata,), available=available)


def service(items=None, **kwargs):
    return MarketDataService(provider(items), FixedClock(START + timedelta(days=1)),
                             InMemoryAuditSink(), **kwargs)


def test_provider_identity_capabilities_range_and_health():
    source = provider()
    assert source.health().name == "HEALTHY"
    assert source.dataset_identity()["dataset_id"] == "DATASET-1"
    assert ProviderCapability.BAR_DATA in source.capabilities()
    assert source.data_range("FICTIONAL_ALPHA", "M15") is not None
    assert source.latest_available_record("FICTIONAL_ALPHA", "M15") == bar(2)


def test_fingerprint_is_deterministic_order_independent_and_materially_sensitive():
    a, b = bar(0), bar(1)
    assert dataset_fingerprint((a, b)) == dataset_fingerprint((b, a))
    assert dataset_fingerprint((a, b)) != dataset_fingerprint((a, bar(1, close=105.0, high=106.0)))


def test_admits_valid_bars_and_assigns_deterministic_ids():
    result = service().validate_and_admit()
    assert result.status is AdmissionStatus.ADMITTED
    assert result.report.overall_health is DataHealth.HEALTHY
    assert all(item.validity is DataValidity.VALID and item.bar_id for item in result.normalized_bars)
    assert result.normalized_bars[0].bar_id == deterministic_bar_id("DATASET-1", bar(0))


@pytest.mark.parametrize("changes", [
    {"high": 98.0}, {"low": 103.0}, {"open": float("nan")},
    {"close": float("inf")}, {"open": -1.0}, {"tick_volume": -1.0},
])
def test_invalid_numeric_or_ohlc_is_rejected(changes):
    result = service((bar(0, **changes),)).validate_and_admit()
    assert result.status is AdmissionStatus.REJECTED
    assert result.report.overall_health is DataHealth.INVALID


def test_unknown_timezone_is_rejected():
    naive = START.replace(tzinfo=None)
    result = service((bar(open_time=naive, close_time=naive + timedelta(minutes=15)),)).validate_and_admit()
    assert result.status is AdmissionStatus.REJECTED
    assert result.report.timestamp_issues == 1


def test_identical_duplicate_is_deduplicated_with_warning():
    item = bar(0)
    result = service((item, item)).validate_and_admit()
    assert result.status is AdmissionStatus.ADMITTED_WITH_WARNINGS
    assert result.report.duplicate_records == 1
    assert len(result.normalized_bars) == 1


def test_conflicting_duplicate_is_rejected_in_strict_mode():
    result = service((bar(0), bar(0, close=100.5))).validate_and_admit()
    assert result.status is AdmissionStatus.REJECTED
    assert result.report.conflicting_duplicates == 1


def test_out_of_order_source_is_rejected_in_strict_mode():
    result = service((bar(1), bar(0))).validate_and_admit()
    assert result.status is AdmissionStatus.REJECTED
    assert any(issue.code == "CHRONOLOGY_INVALID" for issue in result.report.errors)


def test_lenient_import_never_claims_healthy():
    result = service((bar(1), bar(0)), strict=False).validate_and_admit()
    assert result.status is AdmissionStatus.ADMITTED_WITH_WARNINGS
    assert result.report.overall_health is DataHealth.DEGRADED


def test_as_of_and_closed_bar_policy_prevent_look_ahead():
    forming = bar(1, bar_state=BarState.CURRENT_FORMING_BAR, close_time=None)
    svc = service((bar(0), forming)); svc.validate_and_admit()
    decision = START + timedelta(minutes=20)
    assert svc.bars("FICTIONAL_ALPHA", "M15", decision) == (svc.admission.normalized_bars[0],)
    any_state = svc.bars("FICTIONAL_ALPHA", "M15", decision, closed_only=False)
    assert len(any_state) == 2
    before_close = START + timedelta(minutes=10)
    assert svc.bars("FICTIONAL_ALPHA", "M15", before_close) == ()


def test_insufficient_history_unsupported_instrument_and_timeframe_fail_closed():
    svc = service(); svc.validate_and_admit(); as_of = START + timedelta(hours=1)
    assert svc.bars("FICTIONAL_ALPHA", "M15", as_of, required_bars=4) == ()
    assert svc.bars("FICTIONAL_UNKNOWN", "M15", as_of) == ()
    assert svc.bars("FICTIONAL_ALPHA", "D1", as_of) == ()


def test_gap_and_anomaly_classification_preserve_extremes():
    svc = service()
    later = bar(8)
    assert svc.gap_classification(bar(0), later).name == "UNKNOWN_GAP"
    assert svc.gap_classification(bar(0), later, known_closure=True).name == "EXPECTED_CLOSURE"
    extreme = bar(1, open=130, high=140, low=129, close=135)
    assert svc.anomaly(bar(0), extreme) is AnomalyClassification.SUSPECT
    assert svc.anomaly(bar(0), extreme, confirmed_extreme=True) is AnomalyClassification.VALID_EXTREME_EVENT


def test_spread_observed_health_and_unavailable_are_explicit():
    svc = service()
    normal = svc.spread_state((bar(0, spread=.2), bar(1, spread=.2)))
    assert normal.origin is SpreadOrigin.OBSERVED and normal.health is SpreadHealth.NORMAL
    unavailable = svc.spread_state((bar(0, spread=None),))
    assert unavailable.origin is SpreadOrigin.UNAVAILABLE and unavailable.current_spread is None


def test_volume_kinds_and_missing_values_remain_explicit():
    item = bar(tick_volume=None, real_volume=None, volume_kind=VolumeKind.UNAVAILABLE)
    admitted = service((item,)).validate_and_admit().normalized_bars[0]
    assert admitted.tick_volume is None and admitted.real_volume is None
    assert admitted.volume_kind is VolumeKind.UNAVAILABLE


def test_cache_hit_limit_invalidation_and_cross_dataset_isolation():
    cache = BoundedMarketDataCache[int](2)
    one = CacheKey("A", "I", "M15", "1", "CLOSED")
    two = CacheKey("B", "I", "M15", "1", "CLOSED")
    three = CacheKey("C", "I", "M15", "1", "CLOSED")
    cache.put(one, 1); assert cache.get(one) == 1
    cache.put(two, 2); cache.put(three, 3)
    assert len(cache) == 2 and cache.get(one) is None and cache.get(two) == 2
    assert cache.invalidate_fingerprint("B") == 1 and cache.get(three) == 3


def test_new_bar_detection_is_deterministic_and_duplicate_safe():
    svc = service(); admitted = svc.validate_and_admit().normalized_bars[0]
    assert svc.detect_new_bar(admitted).new_closed_bar_available
    assert not svc.detect_new_bar(admitted).new_closed_bar_available
    assert svc.recovery_state()["last_committed_bar_ids"]


def test_snapshot_is_immutable_deterministic_and_provenanced():
    items = []
    for frame in ("M15", "H1", "H4"):
        items.append(bar(0, timeframe=frame, close_time=START + timedelta(minutes=15)))
    svc = service(tuple(items)); svc.validate_and_admit()
    roles = {"context": "H4", "strategy": "H1", "execution": "M15"}
    as_of = START + timedelta(minutes=15)
    first = svc.create_snapshot("FICTIONAL_ALPHA", roles, as_of, experiment_id="EXP-1",
                                configuration_snapshot_id="CFG-1")
    second = svc.create_snapshot("FICTIONAL_ALPHA", roles, as_of, experiment_id="EXP-1",
                                 configuration_snapshot_id="CFG-1")
    assert first and first.snapshot_id == second.snapshot_id
    assert first.data_health is DataHealth.HEALTHY and set(first.provenance) == {"context", "strategy", "execution"}
    with pytest.raises(FrozenInstanceError): first.data_health = DataHealth.INVALID
    with pytest.raises(TypeError): first.provenance["x"] = first.provenance["context"]


def test_invalid_dataset_cannot_publish_snapshot():
    svc = service((bar(high=1.0),)); svc.validate_and_admit()
    assert svc.create_snapshot("FICTIONAL_ALPHA", {"context":"H4","strategy":"H1","execution":"M15"},
                               START, experiment_id="E", configuration_snapshot_id="C") is None


def test_stale_and_unknown_never_become_healthy():
    svc = service(); svc.validate_and_admit()
    selected = svc.bars("FICTIONAL_ALPHA", "M15", START + timedelta(hours=1))
    assert svc.data_health((selected,), START + timedelta(days=1))[0] is DataHealth.STALE
    assert svc.data_health(((),), START)[0] is DataHealth.INCOMPLETE


def test_synchronization_is_time_aware_and_rejects_future_or_stale_components():
    svc = service(); svc.validate_and_admit()
    fresh = (svc.admission.normalized_bars[-1],)
    decision = fresh[-1].close_time
    assert svc.synchronization_status((fresh, fresh), decision).name == "SYNCHRONIZED"
    future = (bar(3),)
    assert svc.synchronization_status((fresh, future), decision).name == "UNSYNCHRONIZED"
    old_h4 = (bar(0, timeframe="H4"),)
    assert svc.synchronization_status((fresh, old_h4), decision + timedelta(hours=20)).name == "UNSYNCHRONIZED"


def test_provider_failure_and_readiness_fail_closed():
    source = provider(available=False)
    svc = MarketDataService(source, FixedClock(START), InMemoryAuditSink())
    ready, reasons = svc.readiness()
    assert not ready and "provider:UNHEALTHY" in reasons
    with pytest.raises(OSError): source.get_bars("FICTIONAL_ALPHA", "M15")
