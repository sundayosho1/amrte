from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.features import (
    FeatureDependencyGraph, FeatureEngine, FeatureHealth, FeatureKey, FeatureRequest,
    FeatureRequirement, PriceSource, ReturnType, atr_series, bollinger_series,
    canonical_parameters, directional_series, ema_series, macd_series, percentile_rank,
    returns, rolling_volatility, rsi_series, true_range_series,
)
from amrte.market.models import (
    BarState, DataHealth, DataValidity, MarketDataSnapshot, NormalizedBar,
    SpreadHealth, SpreadOrigin, SpreadState, SynchronizationStatus,
)

UTC=timezone.utc; START=datetime(2026,1,1,tzinfo=UTC)


def bars(values,timeframe="M15",forming=False):
    return tuple(NormalizedBar("FICTIONAL_ALPHA",timeframe,START+timedelta(minutes=15*i),
        None if forming and i==len(values)-1 else START+timedelta(minutes=15*(i+1)),
        v,v+1,v-1,v+.5,bar_state=BarState.CURRENT_FORMING_BAR if forming and i==len(values)-1 else BarState.CLOSED_BAR,
        validity=DataValidity.VALID,bar_id=f"{timeframe}-{i}") for i,v in enumerate(values))


def snapshot(series,health=DataHealth.HEALTHY,sync=SynchronizationStatus.SYNCHRONIZED,identity="MD"):
    spread=SpreadState(None,None,None,None,None,SpreadHealth.UNAVAILABLE,SpreadOrigin.UNAVAILABLE)
    as_of=series[-1].close_time or series[-1].open_time
    return MarketDataSnapshot(identity,START,as_of,"EXP","DS","FP","FICTIONAL_ALPHA",spread,
        series,series,series,sync,health,100,{},"CFG",0)


def engine(limit=512): return FeatureEngine(FixedClock(START+timedelta(days=1)),InMemoryAuditSink(),maximum_cache_entries=limit)


def test_price_source_definitions():
    from amrte.market.features import price
    item=bars((10,))[0]
    assert price(item,PriceSource.OPEN)==10
    assert price(item,PriceSource.MEDIAN_PRICE)==10
    assert price(item,PriceSource.TYPICAL_PRICE)==pytest.approx(10.1666666667)
    assert price(item,PriceSource.WEIGHTED_CLOSE)==pytest.approx(10.25)


def test_ema_sma_seed_reference_and_wilder_atr_reference():
    ema=ema_series((1,2,3,4,5),3)
    assert ema[:2]==(None,None) and ema[2:]==pytest.approx((2,3,4))
    series=bars((10,11,12,13))
    tr=true_range_series(series)
    assert tr[0]==2 and all(value>=2 for value in tr)
    atr=atr_series(series,3)
    assert atr[2] == pytest.approx(sum(tr[:3])/3)


def test_directional_movement_adx_are_bounded_reference_components():
    plus,minus,adx=directional_series(bars((10,12,11,14,13,16,15,18)),3)
    assert any(item is not None and item>0 for item in plus)
    assert any(item is not None and item>0 for item in minus)
    assert all(item is None or 0<=item<=100 for item in adx)


def test_rsi_rising_falling_flat_edge_cases():
    assert rsi_series(range(20),14)[-1]==100
    assert rsi_series(range(20,0,-1),14)[-1]==0
    assert rsi_series((5,)*20,14)[-1]==50


def test_macd_definition_and_period_validation():
    values=tuple(float(i) for i in range(40)); main,signal,hist=macd_series(values,3,6,3)
    assert main[-1] is not None and signal[-1] is not None
    assert hist[-1]==pytest.approx(main[-1]-signal[-1])
    with pytest.raises(ValueError): macd_series(values,6,3,2)


def test_bollinger_population_reference_and_flat_width():
    middle,upper,lower=bollinger_series((1,2,3),3,2)
    assert middle[-1]==2
    assert upper[-1]==pytest.approx(2+2*(2/3)**.5)
    m,u,l=bollinger_series((5,5,5),3,2); assert u[-1]==l[-1]==m[-1]==5


def test_returns_volatility_and_percentile_ties():
    simple=returns((1,2,4),ReturnType.SIMPLE_RETURN); log=returns((1,2,4),ReturnType.LOG_RETURN)
    assert simple==(None,1,1) and log[1]==pytest.approx(.69314718056)
    vol=rolling_volatility((1,2,3,4,5),2); assert vol[-1] is not None
    assert percentile_rank((1,2,2,3),2)==50


def test_canonical_feature_key_parameter_order_and_isolation():
    assert canonical_parameters({"b":2,"a":1})==canonical_parameters({"a":1,"b":2})
    a=FeatureKey.create("FP","I","M15","EMA",{"period":20,"x":1},PriceSource.CLOSE,BarState.CLOSED_BAR,0,START)
    b=FeatureKey.create("FP","I","M15","EMA",{"x":1,"period":20},PriceSource.CLOSE,BarState.CLOSED_BAR,0,START)
    c=FeatureKey.create("OTHER","I","M15","EMA",{"period":20,"x":1},PriceSource.CLOSE,BarState.CLOSED_BAR,0,START)
    assert a==b and a.identity==b.identity and a!=c


def test_dependency_cycle_rejected():
    graph=FeatureDependencyGraph(); graph.add("A",("B",))
    with pytest.raises(ValueError,match="FEATURE_DEPENDENCY_CYCLE"): graph.add("B",("A",))


@pytest.mark.parametrize("feature_request",[
    FeatureRequest("EMA",{"period":3}),FeatureRequest("TRUE_RANGE",{}),FeatureRequest("ATR",{"period":3}),
    FeatureRequest("ATR_PERCENT_PRICE",{"period":3}),FeatureRequest("PLUS_DI",{"period":3}),
    FeatureRequest("MINUS_DI",{"period":3}),FeatureRequest("ADX",{"period":3}),FeatureRequest("RSI",{"period":3}),
    FeatureRequest("MACD_MAIN",{"fast":2,"slow":4,"signal":2}),FeatureRequest("MACD_SIGNAL",{"fast":2,"slow":4,"signal":2}),
    FeatureRequest("MACD_HISTOGRAM",{"fast":2,"slow":4,"signal":2}),FeatureRequest("MACD_HISTOGRAM_SLOPE",{"fast":2,"slow":4,"signal":2}),
    FeatureRequest("BOLLINGER_MIDDLE",{"period":3,"deviation":2}),FeatureRequest("BOLLINGER_UPPER",{"period":3,"deviation":2}),
    FeatureRequest("BOLLINGER_LOWER",{"period":3,"deviation":2}),FeatureRequest("BOLLINGER_BANDWIDTH",{"period":3,"deviation":2}),
    FeatureRequest("BOLLINGER_PERCENT_B",{"period":3,"deviation":2}),FeatureRequest("CANDLE_RANGE",{}),
    FeatureRequest("CANDLE_BODY",{}),FeatureRequest("CANDLE_UPPER_WICK",{}),FeatureRequest("CANDLE_LOWER_WICK",{}),
    FeatureRequest("CANDLE_BODY_RATIO",{}),FeatureRequest("SIMPLE_RETURN",{}),FeatureRequest("LOG_RETURN",{}),
    FeatureRequest("ROC",{"period":3}),FeatureRequest("RAW_DISPLACEMENT",{"period":3}),
    FeatureRequest("PERCENTAGE_DISPLACEMENT",{"period":3}),FeatureRequest("ATR_ADJUSTED_DISPLACEMENT",{"period":3,"atr_period":3}),
    FeatureRequest("EMA_SEPARATION",{"period":3,"second_period":5}),FeatureRequest("EMA_SLOPE",{"period":3,"lookback":2}),
    FeatureRequest("PRICE_DISTANCE_EMA",{"period":3}),FeatureRequest("REALIZED_VOLATILITY",{"window":3}),
    FeatureRequest("VOLATILITY_PERCENTILE",{"window":3,"percentile_window":5}),FeatureRequest("VOLATILITY_EXPANSION_RATIO",{"window":3,"percentile_window":5}),
    FeatureRequest("RANGE_WIDTH",{"window":3}),FeatureRequest("RANGE_PERCENT_PRICE",{"window":3}),
    FeatureRequest("RANGE_ATR",{"window":3,"atr_period":3}),
])
def test_feature_family_produces_explicit_finite_or_health_state(feature_request):
    series=bars(tuple(100+(i%5)+i*.2 for i in range(40))); source=snapshot(series)
    result=engine().calculate(source,"M15",series,feature_request)
    assert result.health in FeatureHealth
    assert result.value is None or isinstance(result.value,str) or isinstance(result.value,(int,float)) and __import__("math").isfinite(result.value)


def test_shift_and_closed_forming_bar_semantics():
    series=bars(tuple(range(1,12)),forming=True); source=snapshot(series)
    e=engine(); zero=e.calculate(source,"M15",series,FeatureRequest("EMA",{"period":3},shift=0))
    one=e.calculate(source,"M15",series,FeatureRequest("EMA",{"period":3},shift=1))
    forming=e.calculate(source,"M15",series,FeatureRequest("EMA",{"period":3},bar_state=BarState.CURRENT_FORMING_BAR))
    assert zero.source_bar_id==series[-2].bar_id and one.source_bar_id==series[-3].bar_id
    assert forming.source_bar_id==series[-1].bar_id


def test_insufficient_unknown_optional_and_zero_denominator_remain_explicit():
    series=bars((5,)); source=snapshot(series); e=engine()
    assert e.calculate(source,"M15",series,FeatureRequest("EMA",{"period":20})).value is None
    assert e.calculate(source,"M15",series,FeatureRequest("UNKNOWN",{})).health is FeatureHealth.UNAVAILABLE
    flat=tuple(NormalizedBar(**{**item.__dict__,"high":5,"low":5,"open":5,"close":5}) for item in bars((5,5,5)))
    zero=e.calculate(snapshot(flat),"M15",flat,FeatureRequest("CANDLE_BODY_RATIO",{}))
    assert zero.value is None and zero.health is FeatureHealth.NUMERICAL_ERROR


def test_invalid_and_unsynchronized_sources_rejected():
    series=bars(tuple(range(1,30))); requests=(FeatureRequest("EMA",{"period":3}),)
    assert engine().snapshot(snapshot(series,health=DataHealth.INVALID),requests) is None
    assert engine().snapshot(snapshot(series,sync=SynchronizationStatus.UNSYNCHRONIZED),requests) is None


def test_snapshot_mandatory_optional_health_lineage_and_immutability():
    series=bars(tuple(range(1,12))); source=snapshot(series); e=engine()
    optional=e.snapshot(source,(FeatureRequest("EMA",{"period":3}),FeatureRequest("UNKNOWN",{},FeatureRequirement.OPTIONAL)),structure_snapshot_id="STRUCT")
    assert optional.health is FeatureHealth.VALID_WITH_WARNINGS and optional.source_structure_snapshot_id=="STRUCT"
    mandatory=e.snapshot(source,(FeatureRequest("EMA",{"period":30}),))
    assert mandatory.health is FeatureHealth.INSUFFICIENT_HISTORY and not e.readiness(mandatory)[0]
    with pytest.raises(FrozenInstanceError): optional.health=FeatureHealth.INVALID_INPUT
    with pytest.raises(TypeError): optional.features["context"]["x"]=None


def test_temporal_invariance_cache_bounds_and_rebuild_equivalence():
    base=bars(tuple(range(1,31))); extended=bars(tuple(range(1,41)))
    source=snapshot(base); historical=snapshot(extended,identity="MD2")
    historical=MarketDataSnapshot(**{**historical.__dict__,"as_of_timestamp":source.as_of_timestamp})
    request=FeatureRequest("EMA",{"period":5})
    e=engine(limit=2); first=e.calculate(source,"M15",base,request)
    future=e.calculate(historical,"M15",extended,request)
    assert first.value==future.value
    built=e.snapshot(source,(request,)); rebuilt=e.rebuild(source,(request,))
    assert built==rebuilt and len(e.cache)<=2


def test_recovery_and_observability_metadata():
    series=bars(tuple(range(1,15))); audit=InMemoryAuditSink(); e=FeatureEngine(FixedClock(START),audit)
    result=e.snapshot(snapshot(series),(FeatureRequest("EMA",{"period":3}),))
    assert e.recovery_state()["last_feature_snapshot_id"]==result.feature_snapshot_id
    assert {name for name,_ in audit.events}>={"feature_calculation_started","feature_snapshot_created"}
