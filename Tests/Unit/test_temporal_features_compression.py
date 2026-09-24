from dataclasses import replace
from datetime import timedelta

import pytest

from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.features import *
from amrte.market.regime import *
from Tests.Unit.test_events import NOW
from Tests.Unit.test_strategy_framework import intelligence
from Tests.Unit.test_trend_pullback import fv


def snapshots(count=5,vol=.8,band=.1,dataset="FP",config="CFG"):
    base=intelligence().features;items=[]
    for index in range(count):
        at=NOW-timedelta(hours=count-index)
        values={role:dict(features) for role,features in base.features.items()}
        values["strategy"]["VOLATILITY_EXPANSION_RATIO:{}:0"]=replace(fv(vol),as_of_timestamp=at)
        values["strategy"]["BOLLINGER_BANDWIDTH:{}:0"]=replace(fv(band),as_of_timestamp=at)
        items.append(replace(base,feature_snapshot_id=f"F-{dataset}-{index}",as_of_timestamp=at,dataset_fingerprint=dataset,configuration_snapshot_id=config,features=values))
    return tuple(items)


def series(items=None,lookback=3,as_of=NOW,closed=True):
    items=items or snapshots();store=TemporalFeatureSeriesStore(maximum_observations=5,maximum_cache_entries=2)
    for item in items:store.admit(item,"strategy","H1",closed_bar_state=BarState.CLOSED_BAR if closed else BarState.CURRENT_FORMING_BAR)
    result=store.query(dataset_fingerprint=items[0].dataset_fingerprint,instrument_id=items[0].instrument_id,role="strategy",timeframe="H1",as_of=as_of,lookback=lookback,required_features=("VOLATILITY_EXPANSION_RATIO","BOLLINGER_BANDWIDTH"),configuration_snapshot_id=items[0].configuration_snapshot_id)
    return store,result


def test_temporal_identity_bounds_and_deterministic_rebuild():
    items=snapshots(7);store,result=series(items)
    assert store.observation_count==5 and result.observation_count==3 and result.health is TemporalSeriesHealth.HEALTHY
    rebuilt=TemporalFeatureSeriesStore(maximum_observations=5).rebuild(items,"strategy","H1",dataset_fingerprint="FP",instrument_id=items[0].instrument_id,as_of=NOW,lookback=3,required_features=("VOLATILITY_EXPANSION_RATIO","BOLLINGER_BANDWIDTH"),configuration_snapshot_id="CFG")
    assert rebuilt.series_id==result.series_id and rebuilt.observations==result.observations


def test_as_of_excludes_future_and_forming_bar_is_distinct():
    items=snapshots();boundary=items[2].as_of_timestamp;_,historical=series(items,as_of=boundary)
    assert all(item.available_at_utc<=boundary for item in historical.observations)
    _,forming=series(items,closed=False)
    assert forming.observation_count==0 and forming.health is TemporalSeriesHealth.INCOMPLETE


def test_insufficient_missing_cache_dataset_and_configuration_isolation():
    items=snapshots(2);store,result=series(items,lookback=3)
    assert result.health is TemporalSeriesHealth.INSUFFICIENT_HISTORY and result.missing_observations==1
    again=store.query(dataset_fingerprint="FP",instrument_id=items[0].instrument_id,role="strategy",timeframe="H1",as_of=NOW,lookback=3,required_features=("VOLATILITY_EXPANSION_RATIO","BOLLINGER_BANDWIDTH"),configuration_snapshot_id="CFG")
    assert again is result and store.cache_hits==1
    other=store.query(dataset_fingerprint="OTHER",instrument_id=items[0].instrument_id,role="strategy",timeframe="H1",as_of=NOW,lookback=3,required_features=(),configuration_snapshot_id="CFG")
    assert other.observation_count==0


@pytest.mark.parametrize("vol,band,state",[(.7,.1,CompressionState.CONFIRMED),(1.2,.1,CompressionState.PROBABLE),(1.2,.3,CompressionState.NOT_CONFIRMED)])
def test_compression_states(vol,band,state):
    _,temporal=series(snapshots(vol=vol,band=band));result=HistoricalCompressionAnalyzer().analyze(temporal)
    assert result.compression_state is state and 0<=result.compression_score<=100


def test_compression_insufficient_history_and_prebreakout_exclusion():
    items=snapshots(5);_,temporal=series(items,lookback=5)
    analyzer=HistoricalCompressionAnalyzer(CompressionConfiguration(minimum_compression_bars=3,maximum_lookback=5))
    breakout=items[-1].as_of_timestamp;result=analyzer.analyze(temporal,breakout_observation_time=breakout)
    assert result.window_end_utc<breakout and result.breakout_observation_time_utc==breakout
    _,short=series(items[:2],lookback=3);assert analyzer.analyze(short).compression_state is CompressionState.INSUFFICIENT_HISTORY


def test_regime_consumes_series_and_prompt10_contract_remains_compatible():
    intel=intelligence();_,temporal=series();engine=RegimeEngine(__import__("amrte.core.clock",fromlist=["FixedClock"]).FixedClock(NOW),InMemoryAuditSink(),RegimeConfiguration(confirmation_observations=1,minimum_classification_margin=0,cooldown_observations=0))
    result=engine.analyze(intel.market_data,intel.structure,intel.features,temporal_feature_series=temporal)
    assert result.historical_compression.compression_state is CompressionState.CONFIRMED
    assert result.historical_compression.temporal_feature_series_id==temporal.series_id


def test_recovery_and_validation_fail_closed():
    store,_=series();state=store.recovery_state()
    assert store.validate_recovery(state) and not store.validate_recovery({"feature_engine_version":"OLD"})
    with pytest.raises(ValueError):TemporalFeatureSeriesStore(0)
    with pytest.raises(ValueError):HistoricalCompressionAnalyzer(CompressionConfiguration(minimum_compression_bars=5,maximum_lookback=2))
