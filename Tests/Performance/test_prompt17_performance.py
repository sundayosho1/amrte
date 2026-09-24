from time import perf_counter
from tracemalloc import get_traced_memory,start,stop
from amrte.risk.sizing import *
from Tests.Unit.test_risk_sizing import inputs

def test_prompt17_bounded_performance():
    engine=RiskSizingEngine(RiskSizingConfiguration(maximum_cache_entries=64,maximum_decisions=64,maximum_budgets=64));start();begin=perf_counter()
    for i in range(200):
        snap,cap,dist,_=inputs(distance=str(1+(i%9)/10));snap=__import__("dataclasses").replace(snap,snapshot_id=f"RISK-{i}");engine.size(snap,cap,dist)
    elapsed=perf_counter()-begin;_,peak=get_traced_memory();stop();assert len(engine._decisions)<=64 and len(engine._budgets)<=64 and len(engine._cache)<=64 and elapsed<5 and peak<20_000_000
