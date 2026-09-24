from dataclasses import replace
from time import perf_counter

from amrte.strategies.framework import StrategyFrameworkConfiguration
from Tests.Unit.test_strategy_framework import TestStrategy,intelligence,orchestrator


def test_5_strategies_2_instruments_1000_evaluations_are_bounded():
    strategies=tuple(TestStrategy(f"S{i}") for i in range(5))
    engine,_=orchestrator(*strategies,configuration=StrategyFrameworkConfiguration(allowed_instruments=("FICTIONAL_ALPHA","FICTIONAL_BETA"),maximum_cache_entries=64,maximum_history=50))
    base=intelligence();began=perf_counter();signals=no_actions=0
    for index in range(100):
        for instrument in ("FICTIONAL_ALPHA","FICTIONAL_BETA"):
            snapshot=replace(base,instrument_id=instrument,market_intelligence_snapshot_id=f"MI-{instrument}-{index}")
            for result in engine.evaluate_all(snapshot):
                signals+=result.research_signal is not None;no_actions+=result.final_action.name=="NO_ACTION"
    elapsed=perf_counter()-began
    assert signals==1000 and no_actions==0 and elapsed<10 and engine.cache_size==64 and len(engine.history)==50
