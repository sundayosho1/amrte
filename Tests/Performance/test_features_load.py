from datetime import datetime,timedelta,timezone
from time import perf_counter
from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.features import FeatureEngine,FeatureRequest
from amrte.market.models import *


def test_6000_bar_feature_bundle_performance():
    start=datetime(2020,1,1,tzinfo=timezone.utc); frames={}
    for frame in ("H4","H1","M15"):
        frames[frame]=tuple(NormalizedBar("FICTIONAL_ALPHA",frame,start+timedelta(minutes=15*i),start+timedelta(minutes=15*(i+1)),
            100+i/100,101+i/100,99+i/100,100.5+i/100,bar_state=BarState.CLOSED_BAR,validity=DataValidity.VALID,bar_id=f"{frame}-{i}") for i in range(2000))
    spread=SpreadState(None,None,None,None,None,SpreadHealth.UNAVAILABLE,SpreadOrigin.UNAVAILABLE)
    source=MarketDataSnapshot("MD",start,frames["M15"][-1].close_time,"EXP","DS","FP","FICTIONAL_ALPHA",spread,
        frames["H4"],frames["H1"],frames["M15"],SynchronizationStatus.SYNCHRONIZED,DataHealth.HEALTHY,100,{},"CFG",0)
    requests=(FeatureRequest("EMA",{"period":20}),FeatureRequest("ATR",{"period":14}),FeatureRequest("ADX",{"period":14}),
        FeatureRequest("RSI",{"period":14}),FeatureRequest("MACD_HISTOGRAM",{"fast":12,"slow":26,"signal":9}),
        FeatureRequest("BOLLINGER_BANDWIDTH",{"period":20,"deviation":2}),FeatureRequest("REALIZED_VOLATILITY",{"window":20}),
        FeatureRequest("RANGE_ATR",{"window":20,"atr_period":14}))
    engine=FeatureEngine(FixedClock(start),InMemoryAuditSink(),maximum_cache_entries=100)
    began=perf_counter(); result=engine.snapshot(source,requests); elapsed=perf_counter()-began
    assert result is not None and elapsed<5 and len(engine.cache)<=100

