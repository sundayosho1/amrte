from datetime import timedelta
from time import perf_counter

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.events import *
from amrte.market.session import TimeZoneService
from Tests.Unit.test_events import NOW,config,event,provider


def test_2000_events_and_1000_snapshots_are_bounded():
    events=tuple(event(logical=f"E{i}",version=f"E{i}-V1",scheduled=NOW+timedelta(minutes=(i%1440)-720),dimensions=("USD",)) for i in range(2000))
    engine=NewsRiskEngine(FixedClock(NOW),InMemoryAuditSink(),TimeZoneService(),provider(events),config(maximum_cache_entries=64,maximum_history=50))
    began=perf_counter()
    for index in range(1000):engine.analyze(NOW+timedelta(seconds=index),"FICTIONAL_ALPHA","CFG",configuration_hash="PERF")
    elapsed=perf_counter()-began
    assert elapsed<20 and engine.cache_size==64 and len(engine.history)==50
