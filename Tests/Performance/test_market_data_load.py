from datetime import datetime, timedelta, timezone
from time import perf_counter

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.models import BarState, DataValidity, InstrumentMetadata, NormalizedBar, VolumeKind
from amrte.market.provider import DeterministicMarketDataProvider
from amrte.market.service import MarketDataService


def test_bounded_10000_bar_ingestion_and_cache():
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    bars = tuple(NormalizedBar("FICTIONAL_ALPHA", "M15", start + timedelta(minutes=15*i),
        start + timedelta(minutes=15*(i+1)), 100+i/10000, 101+i/10000, 99+i/10000,
        100.5+i/10000, float(i), None, None, BarState.CLOSED_BAR, DataValidity.UNKNOWN,
        str(i), volume_kind=VolumeKind.TICK_VOLUME) for i in range(10000))
    meta = InstrumentMetadata("FICTIONAL_ALPHA", "SYN", supported_timeframes=("M15",))
    provider = DeterministicMarketDataProvider("OFFLINE", "LARGE", "1", bars, (meta,))
    svc = MarketDataService(provider, FixedClock(start), InMemoryAuditSink(), maximum_cache_entries=4)
    began = perf_counter(); result = svc.validate_and_admit(); elapsed = perf_counter() - began
    assert result.status.name == "ADMITTED" and len(result.normalized_bars) == 10000
    selected = svc.bars("FICTIONAL_ALPHA", "M15", bars[-1].close_time)
    assert len(selected) == 10000 and len(svc.cache) <= 4 and elapsed < 5.0

