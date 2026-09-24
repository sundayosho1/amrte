from dataclasses import replace
from time import perf_counter
from tracemalloc import get_traced_memory,start,stop

from amrte.infrastructure.local import InMemoryAuditSink
from amrte.strategies.framework import EvaluationReason,StrategyFrameworkConfiguration,StrategyOrchestrator,StrategyRegistry
from amrte.strategies.scoring import CentralSignalScorer
from amrte.strategies.trend_pullback import S1_STRATEGY_ID,TrendPullbackStrategy
from Tests.Unit.test_events import NOW
from Tests.Unit.test_strategy_framework import FixedClock
from Tests.Unit.test_trend_pullback import bullish


def test_s1_bounded_research_performance():
    audit=InMemoryAuditSink();strategy=TrendPullbackStrategy(audit=audit);registry=StrategyRegistry();registry.register(strategy)
    scorer=CentralSignalScorer(strategy_families={S1_STRATEGY_ID:strategy.metadata.identity.family})
    engine=StrategyOrchestrator(FixedClock(NOW),audit,registry,StrategyFrameworkConfiguration(maximum_cache_entries=32,maximum_history=32),scorer)
    base=bullish();start();begin=perf_counter();signals=0
    for index in range(200):
        item=replace(base,market_intelligence_snapshot_id=f"S1-PERF-{index}")
        result=engine.evaluate(strategy,item,EvaluationReason.NEW_BAR);signals+=result.research_signal is not None
    elapsed=perf_counter()-begin;_,peak=get_traced_memory();stop()
    assert 0<signals<=200 and engine.cache_size==32 and len(engine.history)==32
    assert len(strategy.pullback_history)<=strategy.configuration.maximum_history and elapsed<5 and peak<20_000_000
