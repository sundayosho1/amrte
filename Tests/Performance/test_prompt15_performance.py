from time import perf_counter
from tracemalloc import get_traced_memory,start,stop
from Tests.Unit.test_range_mean_reversion import components,ranged_intel

def test_prompt15_bounded_performance():
    s,e,_=components();start();begin=perf_counter();signals=0
    for i in range(50):
        extreme=ranged_intel(-.05,identity=f"E{i}");inside=ranged_intel(.25,identity=f"I{i}")
        e.evaluate(s,extreme);signals+=e.evaluate(s,inside).research_signal is not None
    elapsed=perf_counter()-begin;_,peak=get_traced_memory();stop()
    assert signals==50 and len(s.range_history)<=s.configuration.maximum_history and elapsed<5 and peak<20_000_000
