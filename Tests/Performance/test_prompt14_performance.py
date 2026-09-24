from dataclasses import replace
from time import perf_counter
from tracemalloc import start,stop,get_traced_memory
from amrte.market.features import TemporalFeatureSeriesStore
from amrte.market.regime import HistoricalCompressionAnalyzer
from amrte.strategies.breakout_volatility import *
from Tests.Unit.test_breakout_strategy import breakout_intel,evaluate
from Tests.Unit.test_temporal_features_compression import snapshots

def test_prompt14_bounded_performance():
    items=snapshots(100);store=TemporalFeatureSeriesStore(maximum_observations=64,maximum_cache_entries=16)
    for item in items:store.admit(item,"strategy","H1")
    start();begin=perf_counter();queries=0
    for lookback in range(3,13):
        series=store.query(dataset_fingerprint="FP",instrument_id=items[0].instrument_id,role="strategy",timeframe="H1",as_of=items[-1].as_of_timestamp,lookback=lookback,required_features=("VOLATILITY_EXPANSION_RATIO","BOLLINGER_BANDWIDTH"),configuration_snapshot_id="CFG");HistoricalCompressionAnalyzer().analyze(series);queries+=1
    strategy,result,_=evaluate(intel=breakout_intel())
    elapsed=perf_counter()-begin;_,peak=get_traced_memory();stop()
    assert queries==10 and store.observation_count==64 and store.cache_size<=16 and result.research_signal is not None
    assert elapsed<5 and peak<20_000_000
