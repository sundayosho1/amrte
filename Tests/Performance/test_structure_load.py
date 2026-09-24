from datetime import datetime, timedelta, timezone
from time import perf_counter

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.models import BarState, DataHealth, DataValidity, MarketDataSnapshot, NormalizedBar, SpreadHealth, SpreadOrigin, SpreadState, SynchronizationStatus
from amrte.market.structure import MarketStructureEngine, StructureConfiguration


def test_bounded_6000_bar_three_timeframe_structure_performance():
    start=datetime(2020,1,1,tzinfo=timezone.utc); frames={}
    for frame in ("H4","H1","M15"):
        frames[frame]=tuple(NormalizedBar("FICTIONAL_ALPHA",frame,start+timedelta(minutes=15*i),
            start+timedelta(minutes=15*(i+1)),100+(i%20)/10,102+(i%20)/10,99+(i%20)/10,
            101+(i%20)/10,bar_state=BarState.CLOSED_BAR,validity=DataValidity.VALID,bar_id=f"{frame}-{i}")
            for i in range(2000))
    spread=SpreadState(None,None,None,None,None,SpreadHealth.UNAVAILABLE,SpreadOrigin.UNAVAILABLE)
    source=MarketDataSnapshot("MD",start,frames["M15"][-1].close_time,"EXP","DS","FP","FICTIONAL_ALPHA",
        spread,frames["H4"],frames["H1"],frames["M15"],SynchronizationStatus.SYNCHRONIZED,
        DataHealth.HEALTHY,100,{},"CFG",0)
    engine=MarketStructureEngine(FixedClock(start),InMemoryAuditSink(),StructureConfiguration(maximum_swings=100,maximum_active_zones=10))
    began=perf_counter(); result=engine.analyze(source); elapsed=perf_counter()-began
    assert result is not None and elapsed < 5 and all(len(item.swings)<=100 and len(item.zones)<=10 for item in
        (result.context_structure,result.strategy_structure,result.execution_structure))
